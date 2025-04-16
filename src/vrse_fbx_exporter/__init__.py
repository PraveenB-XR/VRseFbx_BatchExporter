bl_info = {
    "name": "VRse FBX Batch Exporter",
    "author": "YourName",
    "version": (1, 2, 0), 
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > VRse Exporter",
    "description": "Export objects or collections as FBX with Unity-compatible parameters.",
    "warning": "",
    "doc_url": "",
    "category": "Import-Export",
}

import bpy
from . import VRseFbx_BatchExporter

# Registration
def register():
    VRseFbx_BatchExporter.register()

def unregister():
    VRseFbx_BatchExporter.unregister()

if __name__ == "__main__":
    register()