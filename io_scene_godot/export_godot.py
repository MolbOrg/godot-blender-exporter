# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# ##### END GPL LICENSE BLOCK #####

# Script copyright (C) Juan Linietsky
# Contact Info: juan@godotengine.org

"""
This script is an exporter to Godot Engine

http://www.godotengine.org
"""

import os
import collections
import functools
import logging
import math
import bpy
import mathutils

from . import structures
from . import converters

logging.basicConfig(level=logging.INFO, format="[%(levelname)s]: %(message)s")


@functools.lru_cache(maxsize=1)  # Cache it so we don't search lots of times
def find_godot_project_dir(export_path):
    """Finds the project.godot file assuming that the export path
    is inside a project (looks for a project.godot file)"""
    project_dir = export_path

    # Search up until we get to the top, which is "/" in *nix.
    # Standard Windows ends up as, e.g., "C:\", and independent of what else is
    # in the world, we can at least watch for repeats, because that's bad.
    last = None
    while not os.path.isfile(os.path.join(project_dir, "project.godot")):
        project_dir = os.path.split(project_dir)[0]
        if project_dir == "/" or project_dir == last:
            raise structures.ValidationError(
                "Unable to find godot project file"
            )
        last = project_dir
    logging.info("Found godot project directory at %s", project_dir)
    return project_dir


class ExporterLogHandler(logging.Handler):
    """Custom handler for exporter, would report logging message
    to GUI"""
    def __init__(self, operator):
        super().__init__()
        self.setLevel(logging.WARNING)
        self.setFormatter(logging.Formatter("%(message)s"))

        self.blender_op = operator

    def emit(self, record):
        if record.levelno == logging.WARNING:
            self.blender_op.report({'WARNING'}, record.message)
        else:
            self.blender_op.report({'ERROR'}, record.message)


class GodotExporter:
    """Handles picking what nodes to export and kicks off the export process"""

    def export_node(self, node, parent_gd_node):
        """Recursively export a node. It calls the export_node function on
        all of the nodes children. If you have heirarchies more than 1000 nodes
        deep, this will fail with a recursion error"""

        logging.info("Exporting Blender Object: %s", node.name)

        prev_node = bpy.context.scene.objects.active
        bpy.context.scene.objects.active = node

        # Figure out what function will perform the export of this object
        if node.type in converters.BLENDER_TYPE_TO_EXPORTER:
            exporter = converters.BLENDER_TYPE_TO_EXPORTER[node.type]
        else:
            logging.warning(
                "Unknown object type(%s). Treating as empty: %s", node.type, node.name
            )
            exporter = converters.BLENDER_TYPE_TO_EXPORTER["EMPTY"]

        is_bone_attachment = False
        if ("ARMATURE" in self.config['object_types'] and
                node.parent_bone != ''):
            is_bone_attachment = True
            parent_gd_node = converters.BONE_ATTACHMENT_EXPORTER(
                self.escn_file,
                node,
                parent_gd_node
            )
        try:
            # Perform the export, note that `exported_node.paren`t not
            # always the same as `parent_gd_node`, as sometimes, one
            # blender node exported as two parented node
            exported_node = exporter(self.escn_file, self.config, node,
                                    parent_gd_node)

            if is_bone_attachment:
                for child in parent_gd_node.children:
                    child['transform'] = structures.fix_bone_attachment_transform(
                        node, child['transform']
                    )

            # CollisionShape node has different direction in blender
            # and godot, so it has a -90 rotation around X axis,
            # here rotate its children back
            if exported_node.parent.get_type() == 'CollisionShape':
                exported_node['transform'] *= (
                    mathutils.Matrix.Rotation(math.radians(90), 4, 'X'))

            # if the blender node is exported and it has animation data
            if exported_node != parent_gd_node:
                converters.ANIMATION_DATA_EXPORTER(
                    self.escn_file,
                    self.config,
                    exported_node,
                    node,
                    "transform"
                )

            #children may be not presnt in the scene, linked objects, miltiple scenes
            #so as probably it needs to vet those if they should be exported
            for child in node.children:
                if self.should_export_node(child):
                    #self.export_node(child, exported_node)
                    if self.config["group_export"]:
                        if child.name in self.config["group"].objects:
                            self.export_node(child, exported_node)
                    else:
                        if child.name in self.config["scene"].objects:
                            self.export_node(child, exported_node)

        except IndexError as e:
            logging.warning("node isn't properly exported, children(%d) IndexError : %s" % (len(node.children), e))

        bpy.context.scene.objects.active = prev_node

    def should_export_node(self, node):
        """Checks if a node should be exported:"""
        if node.type not in self.config["object_types"]:
            return False

        if self.config["use_active_layers"]:
            valid = False
            for i in range(20):
                if node.layers[i] and self.scene.layers[i]:
                    valid = True
                    break
            if not valid:
                return False

        if self.config["use_export_selected"] and not node.select:
            return False

        return True

    def export_group(self, group):
        if "gpath" not in self.config:
            self.config['gpath'] = self.config['path']

        fname, fext = os.path.splitext(self.config['gpath'])

        filepath = "%s.grp.%s%s" % (fname, group, fext)
        if os.path.isfile(filepath):
            logging.info("Using saved file for group %s, file: %s" % (group, filepath))
        else:
            logging.info("Save group %s to file %s" % (group, filepath))
            with GodotExporter(filepath, self.config.copy(), self.operator) as exp:
                #Dirty hack group instances may have dupli_offset

                vtx = bpy.data.groups[group].dupli_offset
                vtx = mathutils.Vector((-vtx.x, -vtx.y, -vtx.z))
                exp.scene_transform = mathutils.Matrix([[1.0, 0.0, 0.0, vtx.x], [0.0, 1.0, 0.0, vtx.y], [0.0, 0.0, 1.0, vtx.z]])
                exp.group_export = True
                exp.config["group_export"] = True
                exp.group = bpy.data.groups[group]
                exp.config["group"] = bpy.data.groups[group]
                exp.export()
        group_escn = structures.ExternalResource(filepath, "PackedScene")
        idx = self.escn_file.add_external_resource(group_escn, bpy.data.groups[group])
        if idx > 0 :
            self.config["group_list"][group] = idx

    def export_groups(self, objects):
        # Look if there are instances of groups and export groups first
        #TODO groups and objects _can_ have the same name, reffer by index or group object
        if self.config["group_mode"] != "GROUP_EMPTY":
            grlist = {}
            for obj in objects:
                #logging.info("type %s %s" % (obj.type, obj.dupli_type))
                if obj.type == "EMPTY":
                    if obj.dupli_group != None:
                        if obj.dupli_type == "GROUP":
                            grlist[obj.dupli_group.name] = 0
            logging.info("Exporting %d groups", len(grlist))
            if len(grlist) > 0:
                self.config["group_list"] = {}
                for group in grlist:
                    self.export_group(group)


    def export_group_objects(self):
        """Decide what objects in a group to export, and export them!"""
        # Scene root
        root_gd_node = structures.NodeTemplate(
            self.group.name,
            "Spatial",
            None
        )
        if hasattr(self, "scene_transform"):
            root_gd_node["transform"] = self.scene_transform

        self.escn_file.add_node(root_gd_node)
        logging.info("Exporting Group: %s", self.group.name)


        # Decide what objects to export
        to_export = []
        for obj in self.group.objects:
            # All group objects are valid nodes
            self.valid_nodes.append(obj)

            # No parents outside the group, but keep relations inside the group
            # Children are exported in export_node
            if obj.parent is not None:
                if obj.parent.name not in self.group.objects:
                    to_export.append(obj)
            else:
                to_export.append(obj)

        logging.info("Exporting %d objects", len(self.group.objects))

        #Export groups of instances in the scene as separate scene files
        if self.config["group_mode"] != "GROUP_EMPTY":
            self.export_groups(self.group.objects)

        for obj in to_export:
            self.export_node(obj, root_gd_node)


    def export_scene(self):
        """Decide what objects to export, and export them!"""
        # Scene root
        root_gd_node = structures.NodeTemplate(
            self.scene.name,
            "Spatial",
            None
        )
        if hasattr(self, "scene_transform"):
            root_gd_node["transform"] = self.scene_transform

        self.escn_file.add_node(root_gd_node)
        logging.info("Exporting scene: %s", self.scene.name)

        # Decide what objects to export
        for obj in self.scene.objects:
            if obj in self.valid_nodes:
                continue
            if self.should_export_node(obj):
                # Ensure all parents are also going to be exported
                node = obj
                while node is not None:
                    if node not in self.valid_nodes:
                        self.valid_nodes.append(node)
                    node = node.parent

        logging.info("Exporting %d objects", len(self.valid_nodes))

        #Export groups of instances in the scene as separate scene files
        if self.config["group_mode"] != "GROUP_EMPTY":
            self.export_groups(self.valid_nodes)

        # Instances of groups and linked instances can have parents,
        # which are not in the current scene
        for obj in self.scene.objects:
            if obj in self.valid_nodes:
                if obj.parent is None:
                    self.export_node(obj, root_gd_node)
                elif obj.parent.name not in self.scene.objects:
                    self.export_node(obj, root_gd_node)

    def export(self):
        """Begin the export"""
        self.escn_file = structures.ESCNFile(structures.FileEntry(
            "gd_scene",
            collections.OrderedDict((
                ("load_steps", 1),
                ("format", 2)
            ))
        ))

        if self.group_export:
            self.export_group_objects()
        else:
            self.export_scene()
        self.escn_file.fix_paths(self.config)
        with open(self.path, 'w') as out_file:
            out_file.write(self.escn_file.to_string())

        logging.info("File saved: %s", self.path)

        return True

    def __init__(self, path, kwargs, operator):
        self.path = path
        self.operator = operator
        self.scene = bpy.context.scene
        self.config = kwargs
        self.config["path"] = path
        self.config["project_path_func"] = functools.partial(
            find_godot_project_dir, path
        )
        self.valid_nodes = []

        self.escn_file = None

        self.group_export = False
        self.config["groups"] = bpy.data.groups
        self.config["group_export"] = False
        self.config["scene"] = self.scene

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass


def save(operator, context, filepath="", **kwargs):
    """Begin the export"""
    exporter_log_handler = ExporterLogHandler(operator)
    logging.getLogger().addHandler(exporter_log_handler)

    with GodotExporter(filepath, kwargs, operator) as exp:
        exp.export()

    logging.getLogger().removeHandler(exporter_log_handler)

    return {"FINISHED"}
