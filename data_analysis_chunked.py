"""
Chunked Marine Traffic Data Analysis
Analyzes large GeoTIFF files without loading entire raster into memory
"""

import json
import numpy as np
import rasterio
from rasterio.windows import Window
from pathlib import Path
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt

# Setup
DATASET_DIR = Path("dataset")
OUTPUT_DIR = Path("analysis_outputs")
OUTPUT_DIR.mkdir(exist_ok=True)

log_file = OUTPUT_DIR / "chunked_analysis_log.txt"

def log_print(message):
    """Print and log"""
    print(message)
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(message + '\n')

# Clear log
with open(log_file, 'w', encoding='utf-8') as f:
    f.write("=== CHUNKED RASTER ANALYSIS ===\n\n")

log_print("=" * 80)
log_print("CHUNKED ANALYSIS OF GEOTIFF RASTERS")
log_print("=" * 80)

# Define categories
categories = {
    'Commercial': DATASET_DIR / 'shipdensity_commercial_' / 'ShipDensity_Commercial1.tif',
    'Global': DATASET_DIR / 'shipdensity_global' / 'shipdensity_global.tif',
    'Oil & Gas': DATASET_DIR / 'ShipDensity_OilGas' / 'ShipDensity_OilGas1.tif',
    'Passenger': DATASET_DIR / 'ShipDensity_Passenger' / 'ShipDensity_Passenger1.tif'
}

stats_all = {}

for category, raster_path in categories.items():
    log_print(f"\n{'=' * 70}")
    log_print(f"ANALYZING: {category}")
    log_print(f"{'=' * 70}")
    
    if not raster_path.exists():
        log_print(f"✗ File not found: {raster_path}")
        continue
    
    with rasterio.open(raster_path) as src:
        log_print(f"\nMetadata:")
        log_print(f"  Dimensions: {src.width} x {src.height} = {src.width * src.height:,} pixels")
        log_print(f"  CRS: {src.crs}")
        log_print(f"  Bounds: {src.bounds}")
        log_print(f"  Resolution: {src.transform[0]}° x {-src.transform[4]}°")
        log_print(f"  NoData: {src.nodata}")
        
        # Sample-based statistical analysis
        log_print(f"\nStatistical Sampling (to avoid memory issues):")
        
        # Strategy: Read in chunks
        chunk_size = 1000
        n_samples = 0
        
        # Initialize accumulators
        min_val = float('inf')
        max_val = float('-inf')
        sum_val = 0
        sum_sq = 0
        count_valid = 0
        count_zero = 0
        count_nonzero = 0
        
        # Value bins for distribution
        bin_edges = [0, 1, 10, 100, 1000, 10000, 100000, float('inf')]
        bin_counts = [0] * (len(bin_edges) - 1)
        
        # Sample positions across the raster
        sample_rows = np.linspace(0, src.height - chunk_size, 50, dtype=int)
        sample_cols = np.linspace(0, src.width - chunk_size, 50, dtype=int)
        
        total_chunks = len(sample_rows) * len(sample_cols)
        log_print(f"  Reading {total_chunks} sample chunks ({chunk_size}x{chunk_size} each)...")
        
        chunk_idx = 0
        for row in sample_rows:
            for col in sample_cols:
                # Read window
                window = Window(col, row, min(chunk_size, src.width - col), min(chunk_size, src.height - row))
                data = src.read(1, window=window)
                
                # Filter valid data
                if src.nodata is not None:
                    valid = data[data != src.nodata]
                else:
                    valid = data[~np.isnan(data)]
                
                if valid.size > 0:
                    min_val = min(min_val, valid.min())
                    max_val = max(max_val, valid.max())
                    sum_val += valid.sum()
                    sum_sq += (valid ** 2).sum()
                    count_valid += valid.size
                    count_zero += np.sum(valid == 0)
                    count_nonzero += np.sum(valid > 0)
                    
                    # Bin the data
                    for i in range(len(bin_edges) - 1):
                        if bin_edges[i+1] == float('inf'):
                            bin_counts[i] += np.sum(valid >= bin_edges[i])
                        else:
                            bin_counts[i] += np.sum((valid >= bin_edges[i]) & (valid < bin_edges[i+1]))
                
                chunk_idx += 1
                if chunk_idx % 100 == 0:
                    log_print(f"    Processed {chunk_idx}/{total_chunks} chunks...")
        
        # Calculate statistics
        if count_valid > 0:
            mean_val = sum_val / count_valid
            variance = (sum_sq / count_valid) - (mean_val ** 2)
            std_val = np.sqrt(max(0, variance))
            
            log_print(f"\n  Sample Statistics ({count_valid:,} valid pixels sampled):")
            log_print(f"    Min: {min_val}")
            log_print(f"    Max: {max_val}")
            log_print(f"    Mean: {mean_val:.2f}")
            log_print(f"    Std Dev: {std_val:.2f}")
            log_print(f"    Zero values: {count_zero:,} ({count_zero/count_valid*100:.2f}%)")
            log_print(f"    Non-zero values: {count_nonzero:,} ({count_nonzero/count_valid*100:.2f}%)")
            
            log_print(f"\n  Distribution (AIS position counts):")
            labels = ["No traffic", "Very low (1-10)", "Low (10-100)", "Medium (100-1K)", 
                     "High (1K-10K)", "Very high (10K-100K)", "Extreme (>100K)"]
            for i, (label, count) in enumerate(zip(labels, bin_counts)):
                pct = count / count_valid * 100 if count_valid > 0 else 0
                log_print(f"    {label:20}: {count:10,} ({pct:5.2f}%)")
            
            # Store for comparison
            stats_all[category] = {
                'dimensions': (src.width, src.height),
                'total_pixels': src.width * src.height,
                'sampled_pixels': count_valid,
                'min': float(min_val),
                'max': float(max_val),
                'mean': float(mean_val),
                'std': float(std_val),
                'zero_pct': float(count_zero/count_valid*100) if count_valid > 0 else 0,
                'nonzero_pct': float(count_nonzero/count_valid*100) if count_valid > 0 else 0,
                'distribution': {label: int(count) for label, count in zip(labels, bin_counts)}
            }
        
        log_print(f"\n  Spatial Coverage Analysis:")
        # Read a downsampled version for global view
        downsample = 100
        overview = src.read(1, out_shape=(
            1,
            src.height // downsample,
            src.width // downsample
        ))
        
        # Count non-zero pixels in overview
        if src.nodata is not None:
            valid_overview = overview[overview != src.nodata]
        else:
            valid_overview = overview[~np.isnan(overview)]
        
        nonzero_overview = np.sum(valid_overview > 0)
        coverage_pct = nonzero_overview / valid_overview.size * 100 if valid_overview.size > 0 else 0
        
        log_print(f"    Global coverage (downsampled): {coverage_pct:.2f}% has shipping activity")

# Cross-category comparison
log_print("\n" + "=" * 80)
log_print("CROSS-CATEGORY COMPARISON")
log_print("=" * 80)

if stats_all:
    log_print(f"\n{'Category':<15} {'Dimensions':<20} {'Mean Density':<15} {'Max Density':<15} {'Traffic %':<12}")
    log_print("-" * 85)
    for cat, stats in stats_all.items():
        dims = f"{stats['dimensions'][0]}x{stats['dimensions'][1]}"
        mean_d = f"{stats['mean']:.2f}"
        max_d = f"{stats['max']:.0f}"
        traffic = f"{stats['nonzero_pct']:.2f}%"
        log_print(f"{cat:<15} {dims:<20} {mean_d:<15} {max_d:<15} {traffic:<12}")
    
    # Save to JSON
    with open(OUTPUT_DIR / 'raster_statistics_chunked.json', 'w') as f:
        json.dump(stats_all, f, indent=2)
    log_print(f"\n✓ Statistics saved to: {OUTPUT_DIR / 'raster_statistics_chunked.json'}")

log_print("\n" + "=" * 80)
log_print("ANALYSIS COMPLETE")
log_print("=" * 80)

print(f"\n✓ Analysis complete! Check {log_file.absolute()}")
