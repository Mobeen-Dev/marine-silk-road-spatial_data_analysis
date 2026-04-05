"""
Marine Traffic Data Exploration Script
Comprehensive analysis of Global Shipping Traffic Density datasets
"""

import json
import os
import numpy as np
from pathlib import Path

# Check if geospatial libraries are available
try:
    import rasterio
    from rasterio.plot import show
    RASTERIO_AVAILABLE = True
except ImportError:
    print("WARNING: rasterio not available - install with: pip install rasterio")
    RASTERIO_AVAILABLE = False

try:
    import matplotlib.pyplot as plt
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    print("WARNING: matplotlib not available - install with: pip install matplotlib")
    MATPLOTLIB_AVAILABLE = False

# Setup paths
DATASET_DIR = Path("dataset")
OUTPUT_DIR = Path("analysis_outputs")
OUTPUT_DIR.mkdir(exist_ok=True)

# Log file for all outputs
log_file = OUTPUT_DIR / "exploration_log.txt"

def log_print(message):
    """Print and log to file"""
    print(message)
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(message + '\n')

# Clear previous log
with open(log_file, 'w', encoding='utf-8') as f:
    f.write("=== MARINE TRAFFIC DATA EXPLORATION LOG ===\n\n")

log_print("=" * 80)
log_print("STEP 1: EXPLORING JSON DATA")
log_print("=" * 80)

# Analyze JSON file
json_path = DATASET_DIR / "Global Shipping Traffic Density.json"
if json_path.exists():
    log_print(f"\n✓ Found: {json_path}")
    log_print(f"File size: {json_path.stat().st_size / 1024:.2f} KB")
    
    with open(json_path, 'r', encoding='utf-8') as f:
        json_data = json.load(f)
    
    log_print(f"\nJSON Structure:")
    log_print(f"  Type: {type(json_data)}")
    
    if isinstance(json_data, dict):
        log_print(f"  Keys: {list(json_data.keys())}")
        log_print(f"\nDetailed Content:")
        for key, value in json_data.items():
            log_print(f"\n  [{key}]:")
            log_print(f"    Type: {type(value)}")
            if isinstance(value, (str, int, float, bool)):
                log_print(f"    Value: {value}")
            elif isinstance(value, list):
                log_print(f"    Length: {len(value)}")
                if len(value) > 0:
                    log_print(f"    First item: {value[0]}")
            elif isinstance(value, dict):
                log_print(f"    Sub-keys: {list(value.keys())}")
    
    # Save formatted JSON for reference
    with open(OUTPUT_DIR / "json_formatted.json", 'w', encoding='utf-8') as f:
        json.dump(json_data, f, indent=2)
    log_print(f"\n✓ Saved formatted JSON to: {OUTPUT_DIR / 'json_formatted.json'}")
else:
    log_print(f"✗ JSON file not found: {json_path}")

log_print("\n" + "=" * 80)
log_print("STEP 2: ANALYZING GEOTIFF RASTER FILES")
log_print("=" * 80)

# Define raster files
raster_categories = {
    'commercial': DATASET_DIR / 'shipdensity_commercial_' / 'ShipDensity_Commercial1.tif',
    'global': DATASET_DIR / 'shipdensity_global' / 'shipdensity_global.tif',
    'oil_gas': DATASET_DIR / 'ShipDensity_OilGas' / 'ShipDensity_OilGas1.tif',
    'passenger': DATASET_DIR / 'ShipDensity_Passenger' / 'ShipDensity_Passenger1.tif'
}

raster_stats = {}

if RASTERIO_AVAILABLE:
    for category, raster_path in raster_categories.items():
        log_print(f"\n{'=' * 60}")
        log_print(f"CATEGORY: {category.upper()}")
        log_print(f"{'=' * 60}")
        
        if not raster_path.exists():
            log_print(f"✗ File not found: {raster_path}")
            continue
        
        log_print(f"✓ File exists: {raster_path}")
        log_print(f"  File size: {raster_path.stat().st_size / (1024**2):.2f} MB")
        
        try:
            with rasterio.open(raster_path) as src:
                # Basic metadata
                log_print(f"\nGEOSPATIAL METADATA:")
                log_print(f"  Driver: {src.driver}")
                log_print(f"  Dimensions: {src.width} x {src.height} pixels")
                log_print(f"  Number of bands: {src.count}")
                log_print(f"  Data type: {src.dtypes[0]}")
                log_print(f"  CRS (Coordinate Reference System): {src.crs}")
                log_print(f"  Bounds: {src.bounds}")
                log_print(f"  Transform: {src.transform}")
                
                # Calculate resolution
                pixel_width = src.transform[0]
                pixel_height = -src.transform[4]  # negative because north-up
                log_print(f"\nSPATIAL RESOLUTION:")
                log_print(f"  Pixel width: {pixel_width} degrees")
                log_print(f"  Pixel height: {pixel_height} degrees")
                log_print(f"  Expected ~500m x 500m at equator: {pixel_width:.6f}° ≈ 0.005°")
                
                # Read data
                data = src.read(1)
                
                # Statistical analysis
                log_print(f"\nSTATISTICAL ANALYSIS:")
                log_print(f"  Total pixels: {data.size:,}")
                
                # Handle NoData values
                nodata_value = src.nodata
                log_print(f"  NoData value: {nodata_value}")
                
                if nodata_value is not None:
                    valid_data = data[data != nodata_value]
                else:
                    valid_data = data[~np.isnan(data)]
                
                log_print(f"  Valid data pixels: {valid_data.size:,}")
                log_print(f"  NoData/Invalid pixels: {data.size - valid_data.size:,}")
                log_print(f"  Data coverage: {(valid_data.size / data.size * 100):.2f}%")
                
                if valid_data.size > 0:
                    log_print(f"\nVALUE DISTRIBUTION (Valid pixels only):")
                    log_print(f"  Min: {valid_data.min()}")
                    log_print(f"  Max: {valid_data.max()}")
                    log_print(f"  Mean: {valid_data.mean():.2f}")
                    log_print(f"  Median: {np.median(valid_data):.2f}")
                    log_print(f"  Std Dev: {valid_data.std():.2f}")
                    
                    # Percentiles
                    percentiles = [25, 50, 75, 90, 95, 99]
                    log_print(f"\n  Percentiles:")
                    for p in percentiles:
                        val = np.percentile(valid_data, p)
                        log_print(f"    {p}th: {val:.2f}")
                    
                    # Zero vs non-zero
                    zero_pixels = np.sum(valid_data == 0)
                    nonzero_pixels = np.sum(valid_data > 0)
                    log_print(f"\n  Zero-value pixels: {zero_pixels:,} ({zero_pixels/valid_data.size*100:.2f}%)")
                    log_print(f"  Non-zero pixels: {nonzero_pixels:,} ({nonzero_pixels/valid_data.size*100:.2f}%)")
                    
                    # Density distribution
                    log_print(f"\n  DENSITY RANGES (AIS position counts):")
                    ranges = [
                        (0, 1, "No traffic"),
                        (1, 10, "Very low"),
                        (10, 100, "Low"),
                        (100, 1000, "Medium"),
                        (1000, 10000, "High"),
                        (10000, float('inf'), "Very high")
                    ]
                    for low, high, label in ranges:
                        if high == float('inf'):
                            count = np.sum(valid_data >= low)
                        else:
                            count = np.sum((valid_data >= low) & (valid_data < high))
                        pct = count / valid_data.size * 100
                        log_print(f"    {label:12} [{low:6} - {high if high != float('inf') else '∞':>6}): {count:10,} ({pct:5.2f}%)")
                
                # Store stats for comparison
                raster_stats[category] = {
                    'dimensions': (src.width, src.height),
                    'crs': str(src.crs),
                    'bounds': src.bounds,
                    'resolution': (pixel_width, pixel_height),
                    'valid_pixels': valid_data.size if valid_data.size > 0 else 0,
                    'total_pixels': data.size,
                    'min': float(valid_data.min()) if valid_data.size > 0 else None,
                    'max': float(valid_data.max()) if valid_data.size > 0 else None,
                    'mean': float(valid_data.mean()) if valid_data.size > 0 else None,
                    'median': float(np.median(valid_data)) if valid_data.size > 0 else None
                }
                
        except Exception as e:
            log_print(f"✗ Error reading raster: {e}")

    # Cross-category comparison
    log_print("\n" + "=" * 80)
    log_print("STEP 3: CROSS-CATEGORY COMPARISON")
    log_print("=" * 80)
    
    if raster_stats:
        log_print("\nSUMMARY TABLE:")
        log_print(f"{'Category':<15} {'Dimensions':<20} {'Valid Pixels':<15} {'Mean Density':<15} {'Max Density':<15}")
        log_print("-" * 80)
        for cat, stats in raster_stats.items():
            dims = f"{stats['dimensions'][0]}x{stats['dimensions'][1]}"
            valid = f"{stats['valid_pixels']:,}"
            mean = f"{stats['mean']:.2f}" if stats['mean'] is not None else "N/A"
            max_val = f"{stats['max']:.0f}" if stats['max'] is not None else "N/A"
            log_print(f"{cat:<15} {dims:<20} {valid:<15} {mean:<15} {max_val:<15}")
        
        # Check consistency
        log_print("\nCONSISTENCY CHECKS:")
        dimensions = [stats['dimensions'] for stats in raster_stats.values()]
        crs_list = [stats['crs'] for stats in raster_stats.values()]
        resolutions = [stats['resolution'] for stats in raster_stats.values()]
        
        if len(set(dimensions)) == 1:
            log_print("  ✓ All rasters have same dimensions")
        else:
            log_print("  ✗ WARNING: Rasters have different dimensions")
            for cat, dim in zip(raster_stats.keys(), dimensions):
                log_print(f"    {cat}: {dim}")
        
        if len(set(crs_list)) == 1:
            log_print(f"  ✓ All rasters have same CRS: {crs_list[0]}")
        else:
            log_print("  ✗ WARNING: Rasters have different CRS")
        
        if len(set(resolutions)) == 1:
            log_print(f"  ✓ All rasters have same resolution: {resolutions[0]}")
        else:
            log_print("  ✗ WARNING: Rasters have different resolutions")
        
        # Save stats to JSON
        stats_output = OUTPUT_DIR / "raster_statistics.json"
        with open(stats_output, 'w') as f:
            json.dump(raster_stats, f, indent=2, default=str)
        log_print(f"\n✓ Saved statistics to: {stats_output}")

else:
    log_print("\n✗ Rasterio not available - cannot analyze GeoTIFF files")
    log_print("  Install with: pip install rasterio")

log_print("\n" + "=" * 80)
log_print("STEP 4: DATA QUALITY ASSESSMENT")
log_print("=" * 80)

log_print("\nKEY FINDINGS:")
log_print("1. Data Format: GeoTIFF raster files (0.005° resolution ≈ 500m)")
log_print("2. Categories Available: Commercial, Global, Oil & Gas, Passenger")
log_print("3. Temporal Coverage: Jan 2015 - Feb 2021 (6+ years)")
log_print("4. Data Source: AIS (Automatic Identification System) positions")
log_print("5. Values Represent: Total AIS position reports per grid cell")

log_print("\n" + "=" * 80)
log_print("EXPLORATION COMPLETE")
log_print("=" * 80)
log_print(f"\nAll outputs saved to: {OUTPUT_DIR.absolute()}")
log_print(f"Log file: {log_file.absolute()}")

print("\n✓ Exploration script completed successfully!")
