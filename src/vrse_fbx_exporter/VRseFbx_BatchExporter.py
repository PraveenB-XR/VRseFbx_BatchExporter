bl_info = {
    "name": "VRse FBX Batch Exporter",
    "author": "YourName",
    "version": (1, 2),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > VRse Exporter",
    "description": "Export objects or collections as FBX with Unity-compatible parameters.",
    "warning": "",
    "doc_url": "",
    "category": "Import-Export",
}

import bpy
import os
import platform
from bpy.types import Operator, Panel, PropertyGroup, UIList
from bpy.props import StringProperty, BoolProperty, EnumProperty, CollectionProperty, IntProperty


# -----------------------------------------------------------------------------
# Utility Functions
# -----------------------------------------------------------------------------
def gather_top_level_collections(context):
    """
    Recursively gather all visible collections from the view layer and return
    those with no parent.
    """
    all_visible = set()
    child_to_parent = {}

    def recurse_layer_coll(layer_coll, parent_coll):
        if not layer_coll.hide_viewport and not layer_coll.collection.hide_viewport:
            all_visible.add(layer_coll.collection)
            if parent_coll is not None:
                child_to_parent[layer_coll.collection] = parent_coll
        for child in layer_coll.children:
            recurse_layer_coll(child, layer_coll.collection)

    for lc in context.view_layer.layer_collection.children:
        recurse_layer_coll(lc, None)

    return [c for c in all_visible if c not in child_to_parent]


def all_have_2nd_uv_layer(objects):
    """
    Returns True if at least one mesh is found AND each mesh has >=2 UV layers.
    If no mesh is found, returns False by default.
    """
    mesh_found = False
    for obj in objects:
        if obj.type == 'MESH':
            mesh_found = True
            if len(obj.data.uv_layers) < 2:
                return False
    return mesh_found  # If no meshes found, returns False


def gather_all_objects_recursive(collection, allowed_types):
    """
    Gather all objects from a collection and its child collections.
    """
    all_objects = []
    
    # Add direct objects from this collection
    all_objects.extend([o for o in collection.objects if o.type in allowed_types and not o.hide_viewport])
    
    # Recursively add objects from child collections
    for child_coll in collection.children:
        all_objects.extend(gather_all_objects_recursive(child_coll, allowed_types))
    
    return all_objects


def check_path_exists(path):
    """
    Check if the drive/path exists and is accessible.
    Returns (exists, message)
    """
    # Check if the path exists first
    if os.path.exists(path):
        return True, ""
    
    # For Windows, check if the drive exists
    if platform.system() == "Windows":
        drive = os.path.splitdrive(path)[0]
        if drive and not os.path.exists(drive):
            return False, f"Drive '{drive}' does not exist or is not accessible."
    
    # For other cases, check if the parent directory chain exists
    parent_dir = os.path.dirname(path)
    if parent_dir and not os.path.exists(parent_dir):
        return check_path_exists(parent_dir)
    
    return False, f"Path '{path}' is not accessible."


def ensure_directory_exists(directory_path):
    """
    Ensures a directory exists, creates it if it doesn't.
    Returns (success, message)
    """
    try:
        # First check if the directory or its drive exists
        exists, msg = check_path_exists(os.path.dirname(directory_path))
        if not exists:
            return False, msg
        
        # Try to create the directory if it doesn't exist
        if not os.path.exists(directory_path):
            os.makedirs(directory_path, exist_ok=True)
        return True, ""
    except PermissionError:
        return False, f"Permission denied: Cannot create directory '{directory_path}'"
    except FileNotFoundError:
        return False, f"Path not found: Cannot create directory '{directory_path}'"
    except Exception as e:
        return False, f"Error creating directory '{directory_path}': {str(e)}"


# -----------------------------------------------------------------------------
# Item class for exported files list
# -----------------------------------------------------------------------------
class ExportedFileItem(PropertyGroup):
    """Class for storing name of exported file"""
    name: StringProperty(name="Name")
    file_path: StringProperty(name="Path")


# -----------------------------------------------------------------------------
# Property Group
# -----------------------------------------------------------------------------
class VRseFbxExporterProperties(PropertyGroup):
    export_mode: EnumProperty(
        name="Export Mode",
        description="Export by collections or selected objects",
        items=[
            ('COLLECTIONS', "Collections", "Export objects grouped by their collections"),
            ('SELECTED', "Selected Objects", "Export objects from selection"),
        ],
        default='COLLECTIONS'
    )

    export_path: StringProperty(
        name="Export Path",
        description="Path for exporting FBX files",
        default="",
        subtype='DIR_PATH',
        maxlen=1024
    )

    # Transform Options
    apply_unit: BoolProperty(
        name="Apply Unit",
        description="Apply unit scale to exported meshes",
        default=True
    )
    use_space_transform: BoolProperty(
        name="Use Space Transform",
        description="Apply global space transform to exported meshes",
        default=True
    )
    apply_transform: BoolProperty(
        name="Apply Transform",
        description="Apply object transform (helpful for game engines)",
        default=True
    )
    axis_forward: EnumProperty(
        name="Forward",
        items=(
            ('X', "X Forward", ""),
            ('Y', "Y Forward", ""),
            ('Z', "Z Forward", ""),
            ('-X', "-X Forward", ""),
            ('-Y', "-Y Forward", ""),
            ('-Z', "-Z Forward", "Default"),
        ),
        default='-Z',
    )
    axis_up: EnumProperty(
        name="Up",
        items=(
            ('X', "X Up", ""),
            ('Y', "Y Up", "Default"),
            ('Z', "Z Up", ""),
            ('-X', "-X Up", ""),
            ('-Y', "-Y Up", ""),
            ('-Z', "-Z Up", ""),
        ),
        default='Y',
    )
    apply_scale_options: EnumProperty(
        name="Apply Scalings",
        items=(
            ('FBX_SCALE_NONE', "None", "Don't apply scalings"),
            ('FBX_SCALE_UNITS', "Units", "Apply unit scalings"),
            ('FBX_SCALE_CUSTOM', "Custom", "Apply custom scalings"),
            ('FBX_SCALE_ALL', "All", "Apply all scalings"),
        ),
        default='FBX_SCALE_ALL'
    )
    apply_modifiers: BoolProperty(
        name="Apply Modifiers",
        description="Apply modifiers (e.g. Mirror) before export",
        default=True
    )

    # Export Options for "SELECTED"
    as_single_mesh: BoolProperty(
        name="As Single Mesh",
        description="Combine selected objects into one FBX",
        default=True
    )
    make_separate_folders: BoolProperty(
        name="Make Separate Folders",
        description="If enabled, each object/collection goes in its own subfolder",
        default=False
    )
    
    # Collection Export Options
    separate_child_collections: BoolProperty(
        name="Make folders for Child Collections",
        description="Export child collections into separate subfolders",
        default=False
    )
    combine_nested_collections: BoolProperty(
        name="Combine Nested Collections",
        description="Export all objects from nested collections as a single FBX in the parent folder",
        default=False
    )

    # Object Types to Export - Updated defaults to match the image
    export_empty: BoolProperty(name="Empty", default=False)
    export_camera: BoolProperty(name="Camera", default=False)
    export_lamp: BoolProperty(name="Lamp", default=False)
    export_armature: BoolProperty(name="Armature", default=False)
    export_mesh: BoolProperty(name="Mesh", default=True)
    export_other: BoolProperty(name="Other", default=False)

    # Additional: Export Options
    embed_textures: BoolProperty(
        name="Embed Textures",
        description="Embed textures into the FBX (path_mode='COPY')",
        default=False
    )
    export_animations: BoolProperty(
        name="Export Animations",
        description="Include armature & animations if available",
        default=False
    )
    export_smoothing: EnumProperty(
        name="Smoothing",
        description="Export smoothing mode",
        items=(
            ('EDGE', 'Edge', 'Write edge smoothing'),
            ('FACE', 'Face', 'Write face smoothing'),
            ('OFF', 'Normals Only', 'Normals only'),
        ),
        default='OFF'
    )

    # UI States
    show_transform: BoolProperty(default=True)
    show_other_options: BoolProperty(default=False)
    
    # Track exported files list
    exported_files: CollectionProperty(type=ExportedFileItem)
    exported_files_index: IntProperty()


# -----------------------------------------------------------------------------
# UIList for showing exported files
# -----------------------------------------------------------------------------
class VRSE3D_UL_exported_files(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            if item:
                layout.label(text=item.name, icon='FILE')
        elif self.layout_type in {'GRID'}:
            layout.alignment = 'CENTER'
            layout.label(text="", icon='FILE')


# -----------------------------------------------------------------------------
# Main Export Operator
# -----------------------------------------------------------------------------
class VRSE3D_OT_export_selected(Operator):
    """Export visible Collections or Selected Objects as FBX (Unity compatible)"""
    bl_idname = "object.vrsefbx_export"
    bl_label = "Export as FBX"
    bl_options = {'REGISTER', 'UNDO'}

    directory: StringProperty(
        name="Export Directory",
        description="Choose a directory to export to",
        default="",
        subtype='DIR_PATH'
    )

    def invoke(self, context, event):
        props = context.scene.vrsefbx_exporter
        if props.export_path:
            self.directory = props.export_path
            return self.execute(context)
        else:
            # Open file browser so user can pick an export folder
            context.window_manager.fileselect_add(self)
            return {'RUNNING_MODAL'}

    def get_object_types(self, context):
        props = context.scene.vrsefbx_exporter
        t = set()
        if props.export_empty: t.add('EMPTY')
        if props.export_camera: t.add('CAMERA')
        if props.export_lamp: t.add('LIGHT')
        if props.export_armature: t.add('ARMATURE')
        if props.export_mesh: t.add('MESH')
        if props.export_other: t.add('OTHER')
        return t

    def export_fbx(self, context, filepath, objects):
        """Calls Blender's native FBX exporter with Unity-compatible parameters."""
        if not objects:
            return False  # Safety: if no objects, do nothing

        props = context.scene.vrsefbx_exporter

        # Prepare object types to export based on checkboxes
        ex_object_types = set()
        if props.export_mesh: ex_object_types.add('MESH')
        if props.export_armature or props.export_animations: ex_object_types.add('ARMATURE')
        if props.export_empty: ex_object_types.add('EMPTY')
        if props.export_camera: ex_object_types.add('CAMERA')
        if props.export_lamp: ex_object_types.add('LIGHT')
        if props.export_other: ex_object_types.add('OTHER')

        # Ensure the directory exists
        success, msg = ensure_directory_exists(os.path.dirname(filepath))
        if not success:
            self.report({'ERROR'}, msg)
            return False

        # Ensure we're in OBJECT mode
        if bpy.context.mode != 'OBJECT':
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except Exception:
                pass  # Suppress errors if mode switch fails

        # Deselect all, then select only the valid objects
        bpy.ops.object.select_all(action='DESELECT')
        view_objs = list(context.view_layer.objects)
        valid_objects = [o for o in objects if o in view_objs]
        for o in valid_objects:
            o.select_set(True)

        # Attempt to set the first object as active
        if valid_objects:
            context.view_layer.objects.active = valid_objects[0]

        try:
            # Call FBX export
            bpy.ops.export_scene.fbx(
                check_existing=False,
                filepath=filepath,
                filter_glob="*.fbx",
                use_selection=True,
                object_types=ex_object_types,
                bake_anim=props.export_animations,
                bake_anim_use_all_bones=props.export_animations,
                bake_anim_use_all_actions=props.export_animations,
                use_armature_deform_only=True,
                bake_space_transform=props.apply_transform,
                mesh_smooth_type=props.export_smoothing,
                add_leaf_bones=False,
                embed_textures=props.embed_textures,
                path_mode='COPY' if props.embed_textures else 'AUTO',
                # Transform options
                axis_forward=props.axis_forward,
                axis_up=props.axis_up,
                global_scale=1.0,
                apply_unit_scale=props.apply_unit,
                use_space_transform=props.use_space_transform,
                apply_scale_options=props.apply_scale_options,
                use_mesh_modifiers=props.apply_modifiers,
            )
            
            # Add the exported file to our list
            item = props.exported_files.add()
            item.name = os.path.basename(filepath)
            item.file_path = filepath
            
            return True
        except Exception as e:
            self.report({'ERROR'}, f"Error exporting to {filepath}: {str(e)}")
            return False

    def export_collection_recursive(self, context, collection, parent_dir, allowed_types, create_subfolder=True):
        """Recursively export each collection into a subfolder if needed."""
        props = context.scene.vrsefbx_exporter
        exported_count = 0

        # Create subfolder if needed
        if create_subfolder:
            coll_folder = os.path.join(parent_dir, collection.name)
            success, msg = ensure_directory_exists(coll_folder)
            if not success:
                self.report({'ERROR'}, msg)
                return 0
        else:
            coll_folder = parent_dir

        if props.combine_nested_collections and collection.children:
            # Combine all objects from this collection and its child collections
            all_objects = gather_all_objects_recursive(collection, allowed_types)
            
            if all_objects:
                # Export as a single FBX with parent collection name
                export_path = os.path.join(coll_folder, f"{collection.name}.fbx")
                if self.export_fbx(context, export_path, all_objects):
                    exported_count += 1
        else:
            # Standard export mode - export each collection separately
            # Filter objects in this collection that match allowed_types & are visible
            direct_objs = [
                o for o in collection.objects
                if o.type in allowed_types and not o.hide_viewport
            ]
            
            # If no direct objects, we might still check children
            has_any_direct = bool(direct_objs)

            # Export a single FBX for the direct objects in this collection
            if has_any_direct:
                export_path = os.path.join(coll_folder, f"{collection.name}.fbx")
                if self.export_fbx(context, export_path, direct_objs):
                    exported_count += 1

            # Then handle child collections
            if props.separate_child_collections:
                for child_coll in collection.children:
                    exported_count += self.export_collection_recursive(
                        context, child_coll, coll_folder, allowed_types, create_subfolder=True
                    )
            else:
                for child_coll in collection.children:
                    exported_count += self.export_collection_recursive(
                        context, child_coll, coll_folder, allowed_types, create_subfolder=False
                    )

        return exported_count

    def gather_selected_by_collection(self, selected_objs):
        """Group selected objects by the collections they belong to."""
        coll_map = {}
        for obj in selected_objs:
            for coll in obj.users_collection:
                coll_map.setdefault(coll, []).append(obj)
        return coll_map

    def export_selected_as_collections(self, context, coll_map, parent_coll, parent_dir, visited):
        """Similar recursion for selected objects grouped by collection."""
        exported_count = 0
        if parent_coll in visited:
            return 0
        visited.add(parent_coll)

        coll_folder = os.path.join(parent_dir, parent_coll.name)
        success, msg = ensure_directory_exists(coll_folder)
        if not success:
            self.report({'ERROR'}, msg)
            return 0

        # If we have objects mapped to this collection, export them
        if parent_coll in coll_map:
            objs = coll_map[parent_coll]
            if objs:
                export_path = os.path.join(coll_folder, f"{parent_coll.name}.fbx")
                if self.export_fbx(context, export_path, objs):
                    exported_count += 1

        # Recurse into child collections
        for child in parent_coll.children:
            if child in coll_map:
                exported_count += self.export_selected_as_collections(context, coll_map, child, coll_folder, visited)
        return exported_count

    def export_selected_each_object(self, context, selected_objs, directory):
        """Export each selected object as its own FBX."""
        props = context.scene.vrsefbx_exporter
        export_count = 0
        for obj in selected_objs:
            if props.make_separate_folders:
                obj_folder = os.path.join(directory, obj.name)
                success, msg = ensure_directory_exists(obj_folder)
                if not success:
                    self.report({'ERROR'}, msg)
                    continue
                export_path = os.path.join(obj_folder, f"{obj.name}.fbx")
            else:
                export_path = os.path.join(directory, f"{obj.name}.fbx")
            
            if self.export_fbx(context, export_path, [obj]):
                export_count += 1
        return export_count

    def execute(self, context):
        props = context.scene.vrsefbx_exporter
        
        # Clear previous exported files list
        props.exported_files.clear()
        
        # Convert relative -> absolute path
        self.directory = bpy.path.abspath(self.directory)
        
        # Check if drive/path exists
        exists, msg = check_path_exists(os.path.dirname(self.directory))
        if not exists:
            self.report({'ERROR'}, msg)
            return {'CANCELLED'}
            
        # Try to create the directory
        success, msg = ensure_directory_exists(self.directory)
        if not success:
            self.report({'ERROR'}, msg)
            return {'CANCELLED'}

        orig_sel = context.selected_objects[:]
        orig_active = context.active_object

        allowed_types = self.get_object_types(context)

        if props.export_mode == 'COLLECTIONS':
            top_colls = gather_top_level_collections(context)
            # Filter to collections that have at least 1 visible object in allowed_types
            valid_colls = []
            for c in top_colls:
                col_objs = [o for o in c.all_objects if o.type in allowed_types and not o.hide_viewport]
                if col_objs:
                    valid_colls.append(c)

            export_count = 0
            for coll in valid_colls:
                export_count += self.export_collection_recursive(context, coll, self.directory, allowed_types, True)

            self.report({'INFO'}, f"Exported {export_count} FBX files (Collections mode).")

        else:
            sel_objects = [o for o in context.selected_objects if o.type in allowed_types]
            if not sel_objects:
                self.report({'WARNING'}, "No valid selected objects to export")
                return {'CANCELLED'}

            if props.as_single_mesh and props.make_separate_folders:
                # Group selected objects by collection
                coll_map = self.gather_selected_by_collection(sel_objects)
                all_colls = list(coll_map.keys())
                top_level = []
                for c in all_colls:
                    # Check if c is child of another c
                    is_child = any(
                        (c.name in [child.name for child in other_coll.children])
                        for other_coll in all_colls if other_coll != c
                    )
                    if not is_child:
                        top_level.append(c)

                export_count = 0
                visited = set()
                for top_coll in top_level:
                    export_count += self.export_selected_as_collections(context, coll_map, top_coll, self.directory, visited)

                self.report({'INFO'}, f"Exported {export_count} FBX files (Single Mesh + Separate Folders).")

            elif props.as_single_mesh:
                # All selected objects in a single FBX
                export_name = "combined_export"
                if context.active_object and context.active_object.users_collection:
                    export_name = context.active_object.users_collection[0].name
                export_path = os.path.join(self.directory, f"{export_name}.fbx")
                if self.export_fbx(context, export_path, sel_objects):
                    export_count = 1
                else:
                    export_count = 0
                self.report({'INFO'}, f"Exported single FBX with all selected objects: {export_name}.fbx")

            else:
                # Export each object separately
                export_count = self.export_selected_each_object(context, sel_objects, self.directory)
                self.report({'INFO'}, f"Exported {export_count} objects separately.")

        # Restore original selection and active object
        bpy.ops.object.select_all(action='DESELECT')
        for o in orig_sel:
            if o:
                o.select_set(True)
        if orig_active:
            context.view_layer.objects.active = orig_active

        # Open the exported files dialog if any files were exported
        if len(props.exported_files) > 0:
            bpy.ops.vrse.show_exported_files('INVOKE_DEFAULT')

        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Show Exported Files Dialog
# -----------------------------------------------------------------------------
class VRSE3D_OT_show_exported_files(Operator):
    """Show a list of exported FBX files"""
    bl_idname = "vrse.show_exported_files"
    bl_label = "Exported FBX Files"
    
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)
        
    def draw(self, context):
        layout = self.layout
        props = context.scene.vrsefbx_exporter
        
        layout.label(text="Successfully Exported Files:", icon='CHECKMARK')
        
        # Show files in a UIList
        row = layout.row()
        row.template_list("VRSE3D_UL_exported_files", "", props, "exported_files", 
                          props, "exported_files_index", rows=min(10, len(props.exported_files)))
        
        # Show the total count
        layout.label(text=f"Total Files: {len(props.exported_files)}")
        
        # Add a button to open the export directory
        row = layout.row()
        if len(props.exported_files) > 0:
            file_path = props.exported_files[0].file_path
            export_dir = os.path.dirname(file_path)
            row.operator("wm.path_open", text="Open Export Folder").filepath = export_dir
    
    def execute(self, context):
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Panel
# -----------------------------------------------------------------------------
class VRSE3D_PT_panel(Panel):
    """Panel in the 3D View sidebar for VRse FBX Batch Exporter"""
    bl_label = "VRse FBX Batch Exporter"
    bl_idname = "OBJECT_PT_vrsefbx_auto_exporter"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'VRse Exporter'  # This creates its own separate tab

    def draw(self, context):
        layout = self.layout
        props = context.scene.vrsefbx_exporter

        # Export Mode
        layout.prop(props, "export_mode", expand=True)
        
        # Info Box
        box_top = layout.box()
        
        # Calculate what will be exported
        allowed_types = self.get_allowed_types(props)
        objects_to_check = []
        fbx_count = 0

        if props.export_mode == 'SELECTED':
            selected_objs = [o for o in context.selected_objects if o.type in allowed_types]
            box_top.label(text=f"Selected Objects: {len(selected_objs)}", icon='FILE_TICK')

            if props.as_single_mesh and props.make_separate_folders:
                coll_map = {}
                for obj in selected_objs:
                    for c in obj.users_collection:
                        coll_map.setdefault(c, []).append(obj)
                fbx_count = len(coll_map)
                for group in coll_map.values():
                    objects_to_check.extend(group)
            elif props.as_single_mesh:
                fbx_count = 1 if selected_objs else 0
                objects_to_check = selected_objs
            else:
                fbx_count = len(selected_objs)
                objects_to_check = selected_objs

        else:  # COLLECTIONS Mode
            all_visible = set()
            def gather_layer_coll(lc, out):
                if not lc.hide_viewport and not lc.collection.hide_viewport:
                    out.add(lc.collection)
                for ch in lc.children:
                    gather_layer_coll(ch, out)
            for lc in context.view_layer.layer_collection.children:
                gather_layer_coll(lc, all_visible)

            child_to_parent = {}
            def build_map(lc, parent):
                if not lc.hide_viewport and not lc.collection.hide_viewport:
                    if parent is not None:
                        child_to_parent[lc.collection] = parent
                for ch in lc.children:
                    build_map(ch, lc.collection)
            for lc in context.view_layer.layer_collection.children:
                build_map(lc, None)

            top_level = [c for c in all_visible if c not in child_to_parent]
            valid_colls = []
            for c in top_level:
                col_objs = [o for o in c.all_objects if o.type in allowed_types and not o.hide_viewport]
                if col_objs:
                    valid_colls.append(c)
            fbx_count = len(valid_colls)
            for coll in valid_colls:
                for o in coll.all_objects:
                    if o.type in allowed_types and not o.hide_viewport:
                        objects_to_check.append(o)

            box_top.label(text=f"Active Collections: {len(valid_colls)}", icon='FILE_TICK')

        # Show second UV map info
        has_2nd_uv = all_have_2nd_uv_layer(objects_to_check)
        box_top.label(text=f"Export meshes have 2nd UV map Channel: {'YES' if has_2nd_uv else 'NO'}", icon='UV')
        box_top.label(text=f"Output FBX Count: {fbx_count}", icon='PACKAGE')
        
        # Export path
        layout.prop(props, "export_path")
        
        # EXPORT BUTTON - Added color and renamed
        row_export = layout.row()
        row_export.scale_y = 1.5
        row_export.alignment = 'CENTER'
        op = row_export.operator("object.vrsefbx_export", text="Export as FBX", icon='EXPORT')
        
        # Colorize the button if possible
        try:
            op.bl_ui_units_x = 8  # This makes the button wider
        except:
            pass  # Ignore if property isn't available in this Blender version

        # 1. FOR NESTED COLLECTIONS OPTION
        if props.export_mode == 'COLLECTIONS':
            cbox = layout.box()
            row = cbox.row()
            row.label(text="For nested collections:", icon='OUTLINER_COLLECTION')
            cbox.prop(props, "separate_child_collections")
            cbox.prop(props, "combine_nested_collections")
            
            # Add note that this option overrides separate_child_collections
            if props.combine_nested_collections:
                note_row = cbox.row()
                note_row.label(text="All nested objects will be combined into one FBX", icon='INFO')
        else:
            box_mm = layout.box()
            row_mm = box_mm.row()
            row_mm.label(text="Mesh Merging:")
            box_mm.prop(props, "as_single_mesh")
            box_mm.prop(props, "make_separate_folders")

        # 2. GEOMETRY
        box_geo = layout.box()
        row_geo = box_geo.row()
        row_geo.alert = True
        row_geo.label(text="Geometry *")
        box_geo.prop(props, "apply_modifiers")

        # 3. TRANSFORM COLLAPSE PANEL
        box_trans = layout.box()
        row_trans = box_trans.row()
        row_trans.prop(props, "show_transform", text="", icon="TRIA_DOWN" if props.show_transform else "TRIA_RIGHT", emboss=False)
        row_trans.label(text="Transform")
        if props.show_transform:
            box_trans.prop(props, "apply_unit")
            box_trans.prop(props, "use_space_transform")
            box_trans.prop(props, "apply_transform")
            box_trans.prop(props, "apply_scale_options")
            row_axes = box_trans.row(align=True)
            row_axes.prop(props, "axis_forward")
            row_axes.prop(props, "axis_up")

        # 4. OTHER OPTIONS (combined section for export animations, embed textures, etc.)
        box_other = layout.box()
        row_other = box_other.row()
        row_other.prop(props, "show_other_options", text="", icon="TRIA_DOWN" if props.show_other_options else "TRIA_RIGHT", emboss=False)
        row_other.label(text="Other Options")
        
        if props.show_other_options:
            # Embed Textures
            box_other.prop(props, "embed_textures", text="Embed Textures")
            
            # Export Animations
            box_other.prop(props, "export_animations", text="Export Animations")
            
            # Smoothing
            box_other.prop(props, "export_smoothing", text="Smoothing")
            
            # Object Types
            col = box_other.column(align=True)
            col.label(text="Object Types:")
            col.prop(props, "export_empty")
            col.prop(props, "export_camera")
            col.prop(props, "export_lamp")
            col.prop(props, "export_armature")
            col.prop(props, "export_mesh")
            col.prop(props, "export_other")

    def get_allowed_types(self, props):
        t = set()
        if props.export_empty: t.add('EMPTY')
        if props.export_camera: t.add('CAMERA')
        if props.export_lamp: t.add('LIGHT')
        if props.export_armature: t.add('ARMATURE')
        if props.export_mesh: t.add('MESH')
        if props.export_other: t.add('OTHER')
        return t


# -----------------------------------------------------------------------------
# Registration
# -----------------------------------------------------------------------------
classes = (
    ExportedFileItem,
    VRseFbxExporterProperties,
    VRSE3D_UL_exported_files,
    VRSE3D_OT_export_selected,
    VRSE3D_OT_show_exported_files,
    VRSE3D_PT_panel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.vrsefbx_exporter = bpy.props.PointerProperty(type=VRseFbxExporterProperties)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    if hasattr(bpy.types.Scene, "vrsefbx_exporter"):
        del bpy.types.Scene.vrsefbx_exporter

if __name__ == "__main__":
    register()