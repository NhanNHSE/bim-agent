import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.data_pipeline.ifc_geometry import extract_geometry
result = extract_geometry('/app/data/ifc/Toa_nha_VP_5_tang.ifc')
print(f"Meshes: {len(result['meshes'])}")
print(f"Total elements: {result['stats']['total_elements']}")
print(f"Element types: {result['stats']['element_counts']}")
print(f"BBox min: {result['stats']['bbox_min']}")
print(f"BBox max: {result['stats']['bbox_max']}")
m0 = result['meshes'][0]
print(f"Sample: verts={len(m0['v'])} faces={len(m0['f'])} meta={m0['m']}")
