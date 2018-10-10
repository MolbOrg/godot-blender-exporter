"""
Blender specific functions
"""
import logging

import pdb

def node_matrix(export_settings, node):
    """Get location matrix, can be different choice based on presence of parent nodes"""
    # node can have parent, being an linked instance, or a linked object
    # a parent not present in current scene
    # select matrix_local or matrix_world based on that
    matrix = node.matrix_local
    #pdb.set_trace()
    if node.parent:
        if export_settings["group_export"]:
            if node.parent.name not in export_settings["group"].objects:
                matrix = node.matrix_world
        else:
            if node.parent.name not in export_settings["scene"].objects:
                matrix = node.matrix_world
    #logging.info(matrix)
    return matrix

