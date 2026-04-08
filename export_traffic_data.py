"""
Export Marine Traffic Data for World Map Visualization
Creates shareable CSV datasets from large GeoTIFF rasters
"""

import numpy as np
import rasterio
from pathlib import Path
import json

# Setup paths
DATASET_DIR = Path("dataset")
OUTPUT_DIR = Path("analysis_outputs")
OUTPUT_DIR.mkdir(exist_ok=True)

print("=" * 70)
print("EXPORTING MARINE TRAFFIC DATA FOR VISUALIZATION")
print("=" * 70)

# Category files
categories = {
    'commercial': DATASET_DIR / 'shipdensity_commercial_' / 'ShipDensity_Commercial1.tif',
    'passenger': DATASET_DIR / 'ShipDensity_Passenger' / 'ShipDensity_Passenger1.tif',
    'oil_gas': DATASET_DIR / 'ShipDensity_OilGas' / 'ShipDensity_OilGas1.tif',
}

# Downsample factor (100 = ~50km resolution, manageable file size)
DOWNSAMPLE = 50  # Results in ~1440 x 680 grid

for category, raster_path in categories.items():
    print(f"\n{'=' * 60}")
    print(f"Processing: {category.upper()}")
    print(f"{'=' * 60}")
    
    if not raster_path.exists():
        print(f"✗ File not found: {raster_path}")
        continue
    
    with rasterio.open(raster_path) as src:
        # Read downsampled data
        print(f"Original size: {src.width} x {src.height}")
        new_width = src.width // DOWNSAMPLE
        new_height = src.height // DOWNSAMPLE
        print(f"Downsampled to: {new_width} x {new_height}")
        
        # Read with resampling
        data = src.read(
            1,
            out_shape=(new_height, new_width),
            resampling=rasterio.enums.Resampling.average
        )
        
        # Get transform for coordinate calculation
        # Adjust transform for downsampled resolution
        transform = src.transform
        pixel_width = transform[0] * DOWNSAMPLE
        pixel_height = transform[4] * DOWNSAMPLE  # Negative
        origin_x = transform[2]
        origin_y = transform[5]
        
        nodata = src.nodata
        
        # Filter valid data (non-zero, non-nodata)
        print(f"\nFiltering data...")
        
        # Create coordinate arrays
        rows, cols = np.indices(data.shape)
        
        # Convert to lat/lon
        lons = origin_x + (cols + 0.5) * pixel_width
        lats = origin_y + (rows + 0.5) * pixel_height
        
        # Flatten
        lons_flat = lons.flatten()
        lats_flat = lats.flatten()
        values_flat = data.flatten()
        
        # Filter: keep only non-zero, valid values
        if nodata is not None:
            valid_mask = (values_flat != nodata) & (values_flat > 0)
        else:
            valid_mask = values_flat > 0
        
        lons_valid = lons_flat[valid_mask]
        lats_valid = lats_flat[valid_mask]
        values_valid = values_flat[valid_mask]
        
        print(f"Total pixels: {data.size:,}")
        print(f"Valid (non-zero) pixels: {valid_mask.sum():,}")
        print(f"Data reduction: {(1 - valid_mask.sum()/data.size)*100:.1f}%")
        
        # Apply log transformation for intensity
        intensity = np.log10(values_valid + 1)
        
        # Normalize to 0-1 range
        if intensity.max() > 0:
            intensity_norm = intensity / intensity.max()
        else:
            intensity_norm = intensity
        
        # Create CSV output
        csv_path = OUTPUT_DIR / f"traffic_{category}_world.csv"
        
        print(f"\nWriting CSV: {csv_path}")
        with open(csv_path, 'w') as f:
            f.write("latitude,longitude,density,intensity,intensity_normalized\n")
            for lat, lon, val, inten, inten_norm in zip(
                lats_valid, lons_valid, values_valid, intensity, intensity_norm
            ):
                f.write(f"{lat:.4f},{lon:.4f},{val:.0f},{inten:.4f},{inten_norm:.4f}\n")
        
        file_size = csv_path.stat().st_size / (1024 * 1024)
        print(f"File size: {file_size:.2f} MB")
        print(f"Rows: {valid_mask.sum():,}")
        
        # Also create a smaller "hotspot only" version (top 10% density)
        threshold = np.percentile(values_valid, 90)
        hotspot_mask = values_valid >= threshold
        
        hotspot_path = OUTPUT_DIR / f"traffic_{category}_hotspots.csv"
        print(f"\nWriting hotspot CSV: {hotspot_path}")
        with open(hotspot_path, 'w') as f:
            f.write("latitude,longitude,density,intensity,intensity_normalized\n")
            for lat, lon, val, inten, inten_norm in zip(
                lats_valid[hotspot_mask], 
                lons_valid[hotspot_mask], 
                values_valid[hotspot_mask],
                intensity[hotspot_mask],
                intensity_norm[hotspot_mask]
            ):
                f.write(f"{lat:.4f},{lon:.4f},{val:.0f},{inten:.4f},{inten_norm:.4f}\n")
        
        hotspot_size = hotspot_path.stat().st_size / (1024 * 1024)
        print(f"Hotspot file size: {hotspot_size:.2f} MB")
        print(f"Hotspot rows: {hotspot_mask.sum():,}")
        
        # Statistics summary
        print(f"\nStatistics for {category}:")
        print(f"  Min density: {values_valid.min():.0f}")
        print(f"  Max density: {values_valid.max():.0f}")
        print(f"  Mean density: {values_valid.mean():.2f}")
        print(f"  Median density: {np.median(values_valid):.2f}")

# Create a combined lightweight version (all categories, hotspots only)
print(f"\n{'=' * 60}")
print("Creating combined dataset...")
print(f"{'=' * 60}")

combined_path = OUTPUT_DIR / "traffic_combined_hotspots.csv"
with open(combined_path, 'w') as f:
    f.write("latitude,longitude,density,intensity,category\n")
    
    for category in categories.keys():
        hotspot_file = OUTPUT_DIR / f"traffic_{category}_hotspots.csv"
        if hotspot_file.exists():
            with open(hotspot_file, 'r') as hf:
                next(hf)  # Skip header
                for line in hf:
                    parts = line.strip().split(',')
                    if len(parts) >= 4:
                        f.write(f"{parts[0]},{parts[1]},{parts[2]},{parts[3]},{category}\n")

combined_size = combined_path.stat().st_size / (1024 * 1024)
print(f"Combined hotspots file: {combined_path}")
print(f"Size: {combined_size:.2f} MB")

print(f"\n{'=' * 60}")
print("EXPORT COMPLETE!")
print(f"{'=' * 60}")
print(f"\nOutput files in: {OUTPUT_DIR.absolute()}")
print("\nFiles created:")
for f in OUTPUT_DIR.glob("traffic_*.csv"):
    size = f.stat().st_size / (1024 * 1024)
    print(f"  {f.name}: {size:.2f} MB")

print("\n" + "=" * 70)
print("CSV FORMAT:")
print("=" * 70)
print("""
Columns:
  - latitude: Decimal degrees (WGS84)
  - longitude: Decimal degrees (WGS84)  
  - density: Raw AIS position count
  - intensity: Log10(density + 1) for visualization
  - intensity_normalized: 0-1 scale for heatmaps
  - category: (combined file only) commercial/passenger/oil_gas

Usage with Folium:
  import folium
  from folium.plugins import HeatMap
  import pandas as pd
  
  df = pd.read_csv('traffic_commercial_world.csv')
  heat_data = df[['latitude', 'longitude', 'intensity_normalized']].values.tolist()
  
  m = folium.Map(location=[0, 0], zoom_start=2)
  HeatMap(heat_data, radius=8, blur=10, max_zoom=10).add_to(m)
  m.save('shipping_heatmap.html')

Usage with Plotly:
  import plotly.express as px
  import pandas as pd
  
  df = pd.read_csv('traffic_commercial_world.csv')
  fig = px.density_mapbox(df, lat='latitude', lon='longitude', z='intensity',
                          radius=5, mapbox_style='carto-positron')
  fig.show()
""")
