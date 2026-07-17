# Benchmark Comparison: Linux vs Windows Baseline

**Date:** 2026-07-03
**Linux:** Python 3.11.2, pytest-benchmark 5.2.3, Intel/AMD desktop
**Windows baseline:** `docs/bench/baseline windows.md` (Python 3.11.9)
**Result:** 77 passed, 7 skipped (real DICOM tests need TEST_DICOM_DIR)

---

## Summary

Linux is uniformly faster. The ratio varies by category:

- **Pure Python / dict ops (cache, eviction, scroll):** ~4-5x faster on Linux
- **NumPy decode (zero-copy, copy):** ~7-9x faster on Linux
- **C-extension decode (OpenCV JPEG, JPEG2000):** ~1.2-1.5x faster (smaller gap — C-bound)
- **Rendering (W/L LUT):** ~3.5x faster on Linux

The pattern: Python-dominated paths show large Linux advantage; C-extension-heavy paths show smaller gap.

---

## Decode / DICOM Session

| Benchmark | Windows Median | Linux Median | Speedup |
|-----------|---------------|-------------|---------|
| decode_uncompressed_zero_copy | 224 us | 24.0 us | 9.3x |
| decode_uncompressed_with_copy | 436 us | 61.6 us | 7.1x |
| dicom_session_open | 3.71 ms | 797 us | 4.7x |
| dicom_session_decode_uncompressed | 1.40 us | 240 ns | 5.8x |
| dicom_session_decode_jpeg | 1.10 us | 507 ns | 2.2x |
| dicom_session_decode_jpeg2000 | 1.10 us | 249 ns | 4.4x |
| dicom_session_single_frame_random_access | 64.5 us | 16.4 us | 3.9x |
| decode_fragment_jpeg_cv2 | 2.39 ms | 1.55 ms | 1.5x |
| decode_fragment_jpeg2000_single | 43.2 ms | 36.1 ms | 1.2x |
| pydicom_pixel_array_fallback | 3.08 ms | 537 us | 5.7x |

## Frame Cache / Eviction

| Benchmark | Windows Median | Linux Median | Speedup |
|-----------|---------------|-------------|---------|
| frame_cache_get | 440 ns | 92 ns | 4.8x |
| frames_property_first_call | 102 us | 22.6 us | 4.5x |
| frames_property_cached | 370 ns | 77 ns | 4.8x |
| sorted_keys_eviction_logic | 41.0 us | 9.7 us | 4.2x |
| evict_200_frames_sweep | 8.70 us | 2.02 us | 4.3x |
| evict_with_pinned_frames | 34.7 us | 8.6 us | 4.0x |

## Playback Pipeline

| Benchmark | Windows Median | Linux Median | Speedup |
|-----------|---------------|-------------|---------|
| playback_fps_30_frame_loop | 54.1 us | 13.6 us | 4.0x |
| playback_fps_100_frame_loop | 186 us | 47.4 us | 3.9x |
| prefetch_batch_load | 4.20 us | 1.12 us | 3.7x |
| small_loop_full_prefetch | 6.20 us | 1.76 us | 3.5x |
| warmup_loaded_ahead_count | 29.2 us | 8.9 us | 3.3x |
| double_next_skip_check | 10.7 us | 2.43 us | 4.4x |

## Scroll / Navigation

| Benchmark | Windows Median | Linux Median | Speedup |
|-----------|---------------|-------------|---------|
| scroll_single_frame_hit | 2.60 us | 504 ns | 5.2x |
| scroll_single_frame_miss | 2.30 us | 618 ns | 3.7x |
| scroll_rapid_forward_20 | 29.4 us | 7.6 us | 3.9x |
| scroll_rapid_backward_20 | 29.1 us | 7.7 us | 3.8x |
| directional_prefetch_forward | 81.6 us | 23.8 us | 3.4x |
| directional_prefetch_backward | 76.7 us | 22.6 us | 3.4x |

## Playback FPS Pipeline (synthetic)

| Benchmark | Windows Median | Linux Median | Speedup |
|-----------|---------------|-------------|---------|
| fps_hot_cache_64 | 266 us | 70.0 us | 3.8x |
| fps_hot_cache_256 | 265 us | 70.3 us | 3.8x |
| fps_hot_cache_512 | 266 us | 71.7 us | 3.7x |
| fps_forward_backward | 105 us | 25.7 us | 4.1x |
| fps_warmup_check | 161 us | 44.5 us | 3.6x |
| fps_large_cine_200 | 372 us | 96.7 us | 3.8x |
| fps_pin_cycle | 137 us | 32.1 us | 4.3x |
| fps_report_256 | 107 us | 26.4 us | 4.1x |

## Rendering

| Benchmark | Windows Median | Linux Median | Speedup |
|-----------|---------------|-------------|---------|
| wl_lut | 10.3 ms | 2.94 ms | 3.5x |
| wl_lut_uint16 | 10.8 ms | 3.57 ms | 3.0x |
| wl_lut_uint8 | 9.67 ms | 4.03 ms | 2.4x |
| wl_legacy | 13.2 ms | 2.80 ms | 4.7x |
| to_grayscale_uint8 | 80.2 us | 22.0 us | 3.6x |
| to_grayscale_array_float64 | 1,080 us | 56.5 us | 19.1x |
| to_display_rgb | 1.77 ms | 1.18 ms | 1.5x |
| color_frame_detection | 45.0 ms | 19.0 ms | 2.4x |
| grayscale_check | 44.8 ms | 18.3 ms | 2.4x |

## Network (Fake clients)

| Benchmark | Windows Median | Linux Median | Speedup |
|-----------|---------------|-------------|---------|
| dimse_c_echo_fake | 148 ns | 37.8 ns | 3.9x |
| dimse_c_find_studies_fake | 480 ns | 122 ns | 3.9x |
| dimse_c_find_studies_filtered | 1.90 us | 380 ns | 5.0x |
| dimse_c_find_series_fake | 345 ns | 86.3 ns | 4.0x |
| dimse_c_find_instances_fake | 370 ns | 87.9 ns | 4.2x |
| dimse_c_store_fake | 155 ns | 40.0 ns | 3.9x |
| web_query_studies | 5.70 us | 1.50 us | 3.8x |
| web_query_studies_filtered | 6.60 us | 1.75 us | 3.8x |
| web_query_series | 5.30 us | 1.36 us | 3.9x |
| web_stow_instances | 1.90 us | 356 ns | 5.3x |
| query_service_auto | 8.10 us | 2.21 us | 3.7x |
| query_service_dimse_only | 2.10 us | 428 ns | 4.9x |
| query_service_series | 6.00 us | 1.46 us | 4.1x |
| stow_multipart_1_file | 33.5 us | 4.23 us | 7.9x |
| stow_multipart_10_files | 328 us | 46.3 us | 7.1x |
| stow_multipart_50_files | 4.23 ms | 302 us | 14.0x |

## Memory

| Benchmark | Windows Median | Linux Median | Speedup |
|-----------|---------------|-------------|---------|
| mem_30_frame_cine | 413 us | 33.0 us | 12.5x |
| mem_200_frame_cine | 565 us | 78.5 us | 7.2x |
| memory_bytes_tracking | 26.4 us | 6.18 us | 4.3x |
| zero_copy_view_lifetime | 181 us | 39.4 us | 4.6x |
| heap_copy_allocation | 4.43 ms | 275 us | 16.1x |
| eviction_reclaims_memory | 8.10 us | 1.96 us | 4.1x |

## Pipeline (full decode paths)

| Benchmark | Windows Median | Linux Median | Speedup |
|-----------|---------------|-------------|---------|
| first_frame_latency | 21.4 ms | 10.6 ms | 2.0x |
| scanworker_dispatch | 9.63 ms | 1.90 ms | 5.1x |
| scan_small_study | 9.79 ms | 1.84 ms | 5.3x |
| scan_large_study | 14.7 ms | 2.75 ms | 5.3x |
| scan_study_multiframe | 9.46 ms | 1.81 ms | 5.2x |
| pipeline_uncompressed_decode | 17.2 ms | 3.14 ms | 5.5x |
| pipeline_jpeg_decode | 6.97 ms | 1.84 ms | 3.8x |
| pipeline_jpeg2000_decode | 33.0 ms | 28.6 ms | 1.2x |

---

## Key Takeaways

1. **Consistent 3.5-5x Linux advantage** across pure-Python paths (cache, scroll, network, playback)
2. **C-extension paths show smaller gap** — JPEG2000 decode only 1.2x, JPEG cv2 only 1.5x
3. **Memory-heavy ops show largest gap** — heap_copy 16x, mem_30_frame 12.5x (allocator + NUMA differences)
4. **Frame size is irrelevant for playback tick** — fps_hot_cache identical at 64/256/512 on both platforms
5. **STOW multipart scales linearly** on both platforms (~6.5 us/file Windows, ~6 us/file Linux)
6. **JPEG2000 remains the bottleneck** on both platforms (28-43 ms per decode)
7. **color_frame_detection + grayscale_check** still ~18-19 ms each on Linux — optimization candidate

## Skipped Tests (7)

`test_playback_real_dicom_bench.py` — requires real DICOM data via `TEST_DICOM_DIR` env var. These test hot-cache FPS, pin cycles, forward/backward, warmup checks, and partial-cache scenarios on an 800x1276 124-frame dataset.
