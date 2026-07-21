import tempfile
from pathlib import Path
from src.parser.multi_format_engine import multi_format_engine
from src.parser.ocr_engine import ocr_engine


def test_parallel_batch_extraction():
    # Create 3 temporary text files
    paths = []
    for i in range(3):
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False, encoding="utf-8") as f:
            f.write(f"Test File {i}\nLieferant: Test {i}\nBrutto: {100 + i}.00 EUR")
            paths.append(Path(f.name))
            
    try:
        results = multi_format_engine.extract_batch_parallel(paths, max_workers=4)
        assert len(results) == 3
        for p in paths:
            assert str(p) in results
            assert len(results[str(p)]) == 1
            assert "Test File" in results[str(p)][0]["full_text"]
    finally:
        for p in paths:
            if p.exists():
                p.unlink()


def test_ocr_md5_cache():
    # Test MD5 cache lookup in OCREngine
    from PIL import Image
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp_path = Path(f.name)
    
    img = Image.new("RGB", (100, 50), color="white")
    img.save(tmp_path)
        
    try:
        # First call populates cache
        res1 = ocr_engine.extract_with_quality(tmp_path)
        # Second call hits MD5 cache (0.00s)
        res2 = ocr_engine.extract_with_quality(tmp_path)
        assert res1 == res2
        md5_hash = ocr_engine._compute_md5(tmp_path)
        assert md5_hash in ocr_engine._page_cache
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
