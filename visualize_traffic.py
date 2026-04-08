"""
Marine Traffic Visualization - Interactive World Map
Generates an HTML heatmap of global shipping traffic
"""

import pandas as pd
import folium
from folium.plugins import HeatMap
from pathlib import Path

print("=" * 60)
print("MARINE TRAFFIC VISUALIZATION")
print("=" * 60)

# Paths
DATA_DIR = Path("analysis_outputs")
OUTPUT_DIR = Path("media")
OUTPUT_DIR.mkdir(exist_ok=True)

# Load all three categories
print("\n📂 Loading datasets...")

commercial = pd.read_csv(DATA_DIR / "traffic_commercial_world.csv")
print(f"  Commercial: {len(commercial):,} points")

passenger = pd.read_csv(DATA_DIR / "traffic_passenger_world.csv")
print(f"  Passenger:  {len(passenger):,} points")

oil_gas = pd.read_csv(DATA_DIR / "traffic_oil_gas_world.csv")
print(f"  Oil & Gas:  {len(oil_gas):,} points")

# ============================================================
# MAP 1: Combined Heatmap (All Categories)
# ============================================================
print("\n🗺️  Creating combined heatmap...")

m1 = folium.Map(
    location=[20, 0],
    zoom_start=2,
    tiles='CartoDB dark_matter',
    control_scale=True
)

# Add commercial layer (blue-ish through default)
commercial_data = commercial[['latitude', 'longitude', 'intensity_normalized']].values.tolist()
HeatMap(
    commercial_data,
    radius=6,
    blur=8,
    max_zoom=10,
    gradient={0.2: 'blue', 0.4: 'cyan', 0.6: 'lime', 0.8: 'yellow', 1: 'red'}
).add_to(m1)

# Add title
title_html = '''
<div style="position: fixed; top: 10px; left: 50px; z-index: 1000; 
            background-color: rgba(0,0,0,0.7); padding: 10px 20px; 
            border-radius: 5px; color: white; font-family: Arial;">
    <h3 style="margin: 0;">🚢 Global Marine Traffic Density</h3>
    <p style="margin: 5px 0 0 0; font-size: 12px;">Commercial Shipping (AIS Data 2015-2021)</p>
</div>
'''
m1.get_root().html.add_child(folium.Element(title_html))

map1_path = OUTPUT_DIR / "shipping_heatmap_combined.html"
m1.save(str(map1_path))
print(f"  ✓ Saved: {map1_path}")

# ============================================================
# MAP 2: Category Comparison (Layer Control)
# ============================================================
print("\n🗺️  Creating category comparison map...")

m2 = folium.Map(
    location=[20, 0],
    zoom_start=2,
    tiles='CartoDB positron',
    control_scale=True
)

# Commercial layer (Red/Orange)
fg_commercial = folium.FeatureGroup(name='🚢 Commercial Shipping')
HeatMap(
    commercial[['latitude', 'longitude', 'intensity_normalized']].values.tolist(),
    radius=6,
    blur=8,
    gradient={0.4: 'orange', 0.7: 'red', 1: 'darkred'}
).add_to(fg_commercial)
fg_commercial.add_to(m2)

# Passenger layer (Blue)
fg_passenger = folium.FeatureGroup(name='🛳️ Passenger Ferries & Cruises')
HeatMap(
    passenger[['latitude', 'longitude', 'intensity_normalized']].values.tolist(),
    radius=8,
    blur=10,
    gradient={0.4: 'lightblue', 0.7: 'blue', 1: 'darkblue'}
).add_to(fg_passenger)
fg_passenger.add_to(m2)

# Oil & Gas layer (Green/Yellow)
fg_oilgas = folium.FeatureGroup(name='🛢️ Oil & Gas Platforms')
HeatMap(
    oil_gas[['latitude', 'longitude', 'intensity_normalized']].values.tolist(),
    radius=10,
    blur=12,
    gradient={0.4: 'lightgreen', 0.7: 'green', 1: 'darkgreen'}
).add_to(fg_oilgas)
fg_oilgas.add_to(m2)

# Add layer control
folium.LayerControl(collapsed=False).add_to(m2)

# Add title
title_html2 = '''
<div style="position: fixed; top: 10px; left: 50px; z-index: 1000; 
            background-color: rgba(255,255,255,0.9); padding: 10px 20px; 
            border-radius: 5px; font-family: Arial; box-shadow: 0 2px 6px rgba(0,0,0,0.3);">
    <h3 style="margin: 0; color: #333;">🌊 Marine Traffic by Category</h3>
    <p style="margin: 5px 0 0 0; font-size: 12px; color: #666;">Use layer controls to toggle categories</p>
</div>
'''
m2.get_root().html.add_child(folium.Element(title_html2))

map2_path = OUTPUT_DIR / "shipping_heatmap_categories.html"
m2.save(str(map2_path))
print(f"  ✓ Saved: {map2_path}")

# ============================================================
# MAP 3: Hotspots Only (High Traffic Areas)
# ============================================================
print("\n🗺️  Creating hotspots map...")

m3 = folium.Map(
    location=[30, 50],
    zoom_start=3,
    tiles='CartoDB dark_matter'
)

# Load hotspots
hotspots = pd.read_csv(DATA_DIR / "traffic_combined_hotspots.csv")
print(f"  Hotspots loaded: {len(hotspots):,} points")

# Separate by category for coloring
commercial_hot = hotspots[hotspots['category'] == 'commercial']
passenger_hot = hotspots[hotspots['category'] == 'passenger']
oilgas_hot = hotspots[hotspots['category'] == 'oil_gas']

# Add as circle markers for precision
for _, row in commercial_hot.iterrows():
    folium.CircleMarker(
        location=[row['latitude'], row['longitude']],
        radius=3,
        color='red',
        fill=True,
        fillOpacity=0.6,
        weight=0
    ).add_to(m3)

for _, row in passenger_hot.iterrows():
    folium.CircleMarker(
        location=[row['latitude'], row['longitude']],
        radius=4,
        color='cyan',
        fill=True,
        fillOpacity=0.8,
        weight=0
    ).add_to(m3)

for _, row in oilgas_hot.iterrows():
    folium.CircleMarker(
        location=[row['latitude'], row['longitude']],
        radius=5,
        color='lime',
        fill=True,
        fillOpacity=0.8,
        weight=0
    ).add_to(m3)

# Legend
legend_html = '''
<div style="position: fixed; bottom: 30px; right: 30px; z-index: 1000; 
            background-color: rgba(0,0,0,0.8); padding: 15px; 
            border-radius: 5px; font-family: Arial; color: white;">
    <h4 style="margin: 0 0 10px 0;">🔥 Traffic Hotspots</h4>
    <p style="margin: 5px 0;"><span style="color: red;">●</span> Commercial</p>
    <p style="margin: 5px 0;"><span style="color: cyan;">●</span> Passenger</p>
    <p style="margin: 5px 0;"><span style="color: lime;">●</span> Oil & Gas</p>
</div>
'''
m3.get_root().html.add_child(folium.Element(legend_html))

map3_path = OUTPUT_DIR / "shipping_hotspots.html"
m3.save(str(map3_path))
print(f"  ✓ Saved: {map3_path}")

# ============================================================
# Summary
# ============================================================
print("\n" + "=" * 60)
print("✅ VISUALIZATION COMPLETE!")
print("=" * 60)
print(f"\n📁 Output folder: {OUTPUT_DIR.absolute()}")
print("\n📊 Generated maps:")
print(f"  1. {map1_path.name}")
print("     → Combined heatmap on dark background")
print(f"  2. {map2_path.name}")
print("     → Category comparison with layer toggle")
print(f"  3. {map3_path.name}")
print("     → Precise hotspot markers")

print("\n🌐 To view: Open any HTML file in your browser!")
print(f"\n   Start command:")
print(f"   start media\\shipping_heatmap_combined.html")
print("=" * 60)
