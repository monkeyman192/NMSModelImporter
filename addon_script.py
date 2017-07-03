bl_info = {  
 "name": "NMS Model Toolkit",  
 "author": "gregkwaste, monkeyman192",  
 "version": (0, 9),
 "blender": (2, 7, 0),  
 "location": "File > Export",  
 "description": "Exports to NMS File format",  
 "warning": "",
 "wiki_url": "",  
 "tracker_url": "",  
 "category": "Export"} 
 
import bpy
import bmesh
import os
import sys
from math import radians, degrees
from mathutils import Matrix,Vector

BASEPATH = 'CUSTOMMODELS'

COLDICT = {"MESH": "Mesh",
           "BOX": "Box",
           "CYLINDER": "Cylinder",
           "SPHERE": "Sphere"}

#Attempt to find 'blender.exe path'

for path in sys.path:
    if os.path.isdir(path):
        if 'nms_imp' in os.listdir(path):
            print("Found nms_imp at: ", path)
            os.chdir(path)
            break


# Add script path to sys.path
scriptpath = os.path.join(os.getcwd(),'nms_imp')
#scriptpath = bpy.context.space_data.text.filepath
#scriptpath = "J:\\Projects\\NMS_Model_Importer\\blender_script.py"
#proj_path = os.path.dirname(scriptpath)
#proj_path is set in the parse_material function

print(scriptpath)

if not scriptpath in sys.path:
    sys.path.append(scriptpath)
    #print(sys.path)
    
    
from main import Create_Data
from mbincompiler import mbinCompiler
from classes import TkMaterialData, TkMaterialFlags, TkMaterialUniform, TkMaterialSampler, TkTransformData, TkRotationComponentData
from classes import TkAnimMetadata, TkAnimNodeData, TkAnimNodeFrameData             # imports relating to animations
from classes import TkAnimationComponentData, TkAnimationData                       # entity animation classes
from classes import List, Vector4f
#Import Object Classes
from classes.Object import Model, Mesh, Locator, Reference, Collision, Light, Joint
from LOOKUPS import MATERIALFLAGS

import main
print(main.__file__)

# ExportHelper is a helper class, defines filename and
# invoke() function which calls the file selector.
from bpy_extras.io_utils import ExportHelper
from bpy.props import StringProperty, BoolProperty, EnumProperty, IntProperty, FloatProperty
from bpy.types import Operator


def write_some_data(context, filepath, use_some_setting):
    print("running write_some_data...")
    f = open(filepath, 'w', encoding='utf-8')
    f.write("Hello World %s" % use_some_setting)
    f.close()

    return {'FINISHED'}

def object_is_animated(ob):
    # this will check a blender object to see if it's parent has any anim data (and it's parent recursively)
    if ob.animation_data is not None:
        # in this case just return true that the object has animation data
        return True
    else:
        if ob.parent is not None:
            return object_is_animated(ob.parent)
        else:
            return False

def get_all_actions(obj):
    """Retrieve all actions given a blender object. Includes NLA-actions
       Full credit to this code goes to misnomer on blender.stackexchange
       (cf. https://blender.stackexchange.com/questions/14204/how-to-tell-which-object-uses-which-animation-action)"""
    # slightly modified to return the name of the object, and the action
    if obj.animation_data:
        if obj.animation_data.action:
            yield obj.name, obj.animation_data.action
        for track in obj.animation_data.nla_tracks:
            for strip in track.strips:
                yield obj.name, strip.action

def get_children(obj, curr_children, obj_type, just_names = False):
    # return a flattened list of all the children of an object of a specified type.
    # if just_name is True, then only return the names, otherwise return the actual objects themselves
    for child in obj.children:
        print(child.name, child.NMSNode_props.node_types)
        if child.NMSNode_props.node_types == obj_type:
            if just_names:
                curr_children.append(child.name)
            else:
                curr_children.append(child)
        curr_children += get_children(child, list(), obj_type, just_names)
    return curr_children

""" Misc. functions for transforming data """

#Tangent Calculator
def calc_tangents(faces, verts, norms, uvs):
    tangents = []
    #Init tangents
    for i in range(len(verts)):
        tangents.append(Vector((0,0,0,0)))
    
    #We assume that verts length will be a multiple of 3 since
    #the mesh has been triangulated
    
    trisNum = len(faces)
    #Iterate in triangles
    for i in range(trisNum):
        tri = faces[i]
        vert_1 = tri[0]
        vert_2 = tri[1]
        vert_3 = tri[2]
        
        #Get Point Positions
        P0 = Vector((verts[vert_1]));
        P1 = Vector((verts[vert_2])) - P0;
        P2 = Vector((verts[vert_3])) - P0;
        
        #print('Poss: ', P1, P2)
        
        P0_uv = Vector((uvs[vert_1]))
        P1_uv = Vector((uvs[vert_2])) - P0_uv
        P2_uv = Vector((uvs[vert_3])) - P0_uv
        #Keep only the 1st uvmap
        P1_uv = P1_uv.xy
        P2_uv = P2_uv.xy
        
        
        print('Uvs', P1_uv, P2_uv)
        
        #Matrix determinant
        D = P1_uv[0] * P2_uv[1] - P2_uv[0] * P1_uv[0]
        D = 1.0 / max(D, 0.0001) #Store the inverse right away
        
        #Apply equation
        tang = D * (P2_uv[1] * P1 - P1_uv[1] * P2)
        
        #Orthogonalize Gram-Shmidt
        n = Vector(norms[vert_1]);
        tang = tang - n * tang.dot(n)
        tang.normalize()
        
        #Add to existing
        #Vert_1
        tang1 = Vector(tangents[vert_1]) + tang;
        tang1.normalize()
        tangents[vert_1] = (tang1[0], tang1[1], tang1[2], 1.0)
        #Vert_2
        tang2 = Vector(tangents[vert_2]) + tang;
        tang2.normalize()
        tangents[vert_2] = (tang2[0], tang2[1], tang2[2], 1.0)
        #Vert_3
        tang3 = Vector(tangents[vert_3]) + tang;
        tang3.normalize()
        tangents[vert_3] = (tang3[0], tang3[1], tang3[2], 1.0)
        

    return tangents

def apply_local_transforms(rotmat, verts, norms, tangents):
    norm_mat = rotmat.inverted().transposed()
    
    print(len(verts), len(norms), len(tangents))
    for i in range(len(verts)):
        #Load Vertex
        vert = rotmat * Vector((verts[i]))
        #Store Transformed
        verts[i] = (vert[0], vert[1], vert[2], 1.0)
        #Load Normal
        norm = norm_mat * Vector((norms[i]))
        norm.normalize()
        #Store Transformed normal
        norms[i] = (norm[0], norm[1], norm[2], 1.0)
        #Load Tangent
        tang = norm_mat * Vector((tangents[i]))
        tang.normalize()
        #Store Transformed tangent
        tangents[i] = (tang[0], tang[1], tang[2], 1.0)

def transform_to_NMS_coords(ob):
    # this will return the local transform, rotation and scale of the object in the NMS coordinate system
    matrix = ob.matrix_local
    yzmat = Matrix()
    yzmat[0] = Vector((1.0, 0.0, 0.0, 0.0))
    yzmat[1] = Vector((0.0, 0.0, 1.0, 0.0))
    yzmat[2] = Vector((0.0, 1.0, 0.0, 0.0))
    yzmat[3] = Vector((0.0, 0.0, 0.0, 1.0))
    
    return (yzmat * ob.matrix_local * yzmat).decompose()


""" Main exporter class with all the other functions contained in one place """

class Exporter():
    # class to contain all the exporting functions

    def __init__(self, exportpath):
        self.global_scene = bpy.context.scene
        self.global_scene.frame_set(0)      # set the frame to be the first one, just in case an export has already been run
        self.mname = os.path.basename(exportpath)

        self.state = None
        
        icounter = 0
        vcounter = 0
        vertices = []
        normals  = [] 
        indices  = []
        uvs      = []
        tangents = []

        materials = []
        collisions = []
        self.material_dict = {}
        self.material_ids = []
        
        self.anim_frame_data = dict()

        self.joints = 0     # current number of joints. This is incremented as required.
        
        #Try to fetch NMS_SCENE node
        try:
            self.NMSScene = self.global_scene.objects['NMS_SCENE']
        except:
            raise Exception("Missing NMS_SCENE Node, Create it!")

        # check whether or not we will be exporting in batch mode
        if self.NMSScene.NMSScene_props.batch_mode:
            batch_export = True
        else:
            batch_export = False

        # if there is a name for the group, use it.
        if self.NMSScene.NMSScene_props.group_name != "":
            self.group_name = self.NMSScene.NMSScene_props.group_name
        else:
            self.group_name = self.mname

        # if we aren't doing a batch export, set the scene as a model object that all will use as a parent
        if batch_export == False:
            #Create main scene model now
            scene = Model(Name = self.mname)

        # pre-process the animation information.
        self.scene_actions = set()      # set to contain all the actions that are used in the scene
        self.joint_anim_data = dict()
        self.anim_controller_obj = None     # this is the Mesh object that was specified as controlling the animations


        # get all the animation data first, so we can decide how we deal with anims. This data can be used to determine how many animations we actually have.
        self.add_to_anim_data(self.NMSScene)
        self.anim_frames = self.global_scene.frame_end        # number of frames        (same... for now)
        print(self.scene_actions)
        print(self.joint_anim_data)

        # create any commands that need to be sent to the main script:
        commands = {'dont_compile': self.NMSScene.NMSScene_props.dont_compile}

        """ This will probably need to be re-worked to make sure it works... """
        for ob in self.NMSScene.children:
            if not ob.name.startswith('NMS'):
                continue
            print('Located Object for export', ob.name)
            if batch_export:
                # we will need to create an individual scene object for each mesh
                if len(ob.name.split('_')) == 2:        # this check needs to be changed to something more... good...
                    if 'REFERENCE' not in ob.name:
                        name = ob.name.split('_')[1]
                        self.scene_directory = os.path.join(BASEPATH, self.group_name, name)
                        print("Processing object {}".format(name))
                        scene = Model(Name = name)
                        self.parse_object(ob, scene)#, scn, process_anim = animate is not None, anim_frame_data = anim_frame_data, extra_data = extra_data)
                        anim = self.anim_generator()
                        directory = os.path.dirname(exportpath)
                        mpath = os.path.dirname(os.path.abspath(exportpath))
                        os.chdir(mpath)
                        Create_Data(name,
                                    self.group_name,
                                    scene,
                                    anim,
                                    **commands)
                        
            else:
                # parse the entire scene all in one go.
                self.scene_directory = os.path.join(BASEPATH, self.group_name, self.mname)      # set this here because... why not
                self.parse_object(ob, scene)#, scn, process_anim = animate is not None, anim_frame_data = anim_frame_data, extra_data = extra_data)

        self.process_anims()

        print('Creating .exmls')
        #Convert Paths
        if not batch_export:
            # we only want to run this if we aren't doing a batch export
            directory = os.path.dirname(exportpath)
            mpath = os.path.dirname(os.path.abspath(exportpath))
            os.chdir(mpath)
            # create the animation stuff if necissary:
            print('bloop')
            anim = self.anim_generator()
            Create_Data(self.mname,
                        self.group_name,
                        scene,
                        anim,
                        **commands)

        self.state = 'FINISHED'

    def add_to_anim_data(self, ob):
        for child in ob.children:
            if child.NMSNode_props.node_types == "Joint":
                # iterate over each child that is a joint
                for name_action in get_all_actions(child):
                    self.scene_actions.add(name_action[1])
                    if name_action[0] not in self.joint_anim_data:
                        self.joint_anim_data[name_action[0]] = [name_action[1]]
                    else:
                        self.joint_anim_data[name_action[0]].append(name_action[1])
            self.add_to_anim_data(child)                    

    def parse_material(self, ob):
        # This function returns a tkmaterialdata object with all necessary material information
        
        #Get Material stuff
        if ob.get('MATERIAL', None) is not None:
            # if a material path has been specified simply use that
            matpath = str(ob['MATERIAL'])
            return matpath
        else:
            # otherwise parse the actual material data
            slot = ob.material_slots[0]
            mat = slot.material
            print(mat.name)

            proj_path = bpy.path.abspath('//')
            
            #Create the material
            matflags = List()
            matsamplers = List()
            matuniforms = List()
            
            tslots = mat.texture_slots
            
            #Fetch Uniforms
            matuniforms.append(TkMaterialUniform(Name="gMaterialColourVec4",
                                                 Values=Vector4f(x=mat.diffuse_color.r,
                                                                 y=mat.diffuse_color.g,
                                                                 z=mat.diffuse_color.b,
                                                                 t=1.0)))
            matuniforms.append(TkMaterialUniform(Name="gMaterialParamsVec4",
                                                 Values=Vector4f(x=0.0,
                                                                 y=0.0,
                                                                 z=0.0,
                                                                 t=0.0)))
            matuniforms.append(TkMaterialUniform(Name="gMaterialSFXVec4",
                                                 Values=Vector4f(x=0.0,
                                                                 y=0.0,
                                                                 z=0.0,
                                                                 t=0.0)))
            matuniforms.append(TkMaterialUniform(Name="gMaterialSFXColVec4",
                                                 Values=Vector4f(x=0.0,
                                                                 y=0.0,
                                                                 z=0.0,
                                                                 t=0.0)))
            #Fetch Diffuse
            texpath = ""
            if tslots[0]:
                #Set _F01_DIFFUSEMAP
                matflags.append(TkMaterialFlags(MaterialFlag=MATERIALFLAGS[0]))
                #Create gDiffuseMap Sampler
                
                tex = tslots[0].texture
                #Check if there is no texture loaded
                if not tex.type=='IMAGE':
                    raise Exception("Missing Image in Texture: " + tex.name)
                
                texpath = os.path.join(proj_path, tex.image.filepath[2:])
            print(texpath)
            sampl = TkMaterialSampler(Name="gDiffuseMap", Map=texpath, IsSRGB=True)
            matsamplers.append(sampl)
            
            #Check shadeless status
            if (mat.use_shadeless):
                #Set _F07_UNLIT
                matflags.append(TkMaterialFlags(MaterialFlag=MATERIALFLAGS[6]))    
            
            #Fetch Mask
            texpath = ""
            if tslots[1]:
                #Set _F24_AOMAP
                #matflags.append(TkMaterialFlags(MaterialFlag=MATERIALFLAGS[23]))
                #Create gMaskMap Sampler
                
                tex = tslots[1].texture
                #Check if there is no texture loaded
                if not tex.type=='IMAGE':
                    raise Exception("Missing Image in Texture: " + tex.name)
                
                texpath = os.path.join(proj_path, tex.image.filepath[2:])
            
            sampl = TkMaterialSampler(Name="gMaskMap", Map=texpath, IsSRGB=False)
            matsamplers.append(sampl)
            
            #Fetch Normal Map
            texpath = ""
            if tslots[2]:
                #Set _F03_NORMALMAP
                matflags.append(TkMaterialFlags(MaterialFlag=MATERIALFLAGS[2]))
                #Create gNormalMap Sampler
                
                tex = tslots[2].texture
                #Check if there is no texture loaded
                if not tex.type=='IMAGE':
                    raise Exception("Missing Image in Texture: " + tex.name)
                
                texpath = os.path.join(proj_path, tex.image.filepath[2:])
            
            sampl = TkMaterialSampler(Name="gNormalMap", Map=texpath, IsSRGB=False)
            matsamplers.append(sampl)

            matflags.append(TkMaterialFlags(MaterialFlag=MATERIALFLAGS[46]))
            
            #Create materialdata struct
            tkmatdata = TkMaterialData(Name=mat.name,
                                       Class='Opaque',
                                       Flags=matflags,
                                       Uniforms=matuniforms,
                                       Samplers=matsamplers)
                
            return tkmatdata

    def anim_generator(self):
        # process the anim data into a TkAnimMetadata structure
        joint_list = get_children(self.NMSScene, list(), "Joint", just_names = True)        # list of the names of every joint
        print("joint list:", joint_list)
        num_nodes = len(joint_list)
        AnimationFiles = {}
        for action in self.anim_frame_data:
            action_data = self.anim_frame_data[action]
            NodeData = List()
            active_nodes = list(action_data.keys())
            print("active nodes ", active_nodes, " for {}".format(action))
            ordered_nodes = list() + active_nodes                # list of all the nodes with the ones with animation data first (empty ones will be appended on)
            for node in joint_list:
                # only need to add on empty ones to the end
                if node not in active_nodes:
                    ordered_nodes.append(node)
            print(ordered_nodes)
            for node in range(num_nodes):
                kwargs = {'Node': ordered_nodes[node][len("NMS_"):], 'RotIndex': str(node), 'TransIndex': str(node), 'ScaleIndex': str(node)}
                NodeData.append(TkAnimNodeData(**kwargs))
            AnimFrameData = List()
            stillRotations = List()
            stillTranslations = List()
            stillScales = List()
            for frame in range(self.anim_frames):
                Rotations = List()
                Translations = List()
                Scales = List()
                # the active nodes will be in the same order as the ordered list because we constructed it that way
                # only iterate over the active nodes
                for node in active_nodes:
                    trans = action_data[node][frame][0]
                    rot = action_data[node][frame][1]
                    scale = action_data[node][frame][2]
                    Rotations.append(Vector4f(x = rot[0], y = rot[1], z = rot[2], t = rot[3]))
                    Translations.append(Vector4f(x = trans[0], y = trans[1], z = trans[2], t = 1.0))
                    Scales.append(Vector4f(x = scale[0], y = scale[1], z = scale[2], t = 1.0))
                    if frame == 0:
                        stillRotations.append(Vector4f(x = rot[0], y = rot[1], z = rot[2], t = rot[3]))
                        stillTranslations.append(Vector4f(x = trans[0], y = trans[1], z = trans[2], t = 1.0))
                        stillScales.append(Vector4f(x = scale[0], y = scale[1], z = scale[2], t = 1.0))
                FrameData = TkAnimNodeFrameData(Rotations = Rotations, Translations = Translations, Scales = Scales)
                AnimFrameData.append(FrameData)
            StillFrameData = TkAnimNodeFrameData(Rotations = stillRotations, Translations = stillTranslations, Scales = stillScales)

            AnimationFiles[action] = (TkAnimMetadata(FrameCount = str(self.anim_frames),
                                                     NodeCount = str(num_nodes),
                                                     NodeData = NodeData,
                                                     AnimFrameData = AnimFrameData,
                                                     StillFrameData = StillFrameData))
        return AnimationFiles
        
    #Main Mesh parser
    def mesh_parser(self, ob):
        #Lists
        verts = []
        norms = []
        tangents = []
        luvs = []
        faces = []
        # Matrices
        object_matrix_wrld = ob.matrix_world
        rot_x_mat = Matrix.Rotation(radians(-90), 4, 'X')
        scale_mat = Matrix.Scale(1, 4)
        norm_mat = rot_x_mat.inverted().transposed()
        
        data = ob.data
        #Raise exception if UV Map is missing
        uvcount = len(data.uv_layers)
        if (uvcount < 1):
            raise Exception("Missing UV Map")
            
        
        #data.update(calc_tessface=True)  # convert ngons to tris
        data.calc_tessface()
        #try:
            #pass
        #    data.calc_tangents(data.uv_layers[0].name)
        #except:
        #    raise Exception("Please Triangulate your Mesh")
        
        colcount = len(data.vertex_colors)
        id = 0
        for f in data.tessfaces:  # indices
            #polygon = data.polygons[f.index] #Load Polygon
            if len(f.vertices) == 4:
                faces.append((id, id + 1, id + 2))
                faces.append((id, id + 2, id + 3))
                id += 4
            else:
                faces.append((id, id + 1, id + 2))
                id += 3

            for vert in range(len(f.vertices)):
                #Store them untransformed and we will fix them after tangent calculation
                co = data.vertices[f.vertices[vert]].co
                #norm = data.vertices[f.vertices[vert]].normal #Save Vertex Normal
                norm = f.normal #Save face normal
                
                #norm =    100 * norm_mat * data.loops[f.vertices[vert]].normal
                #tangent = 100 * norm_mat * data.loops[f.vertices[vert]].tangent
                verts.append((co[0], co[1], co[2], 1.0)) #Invert YZ to match NMS game coords
                norms.append((norm[0], norm[1], norm[2], 1.0))
                #tangents.append((tangent[0], tangent[1], tangent[2], 0.0))

                #Get Uvs
                uv = getattr(data.tessface_uv_textures[0].data[f.index], 'uv'+str(vert + 1))
                luvs.append((uv.x, 1.0 - uv.y, 0.0, 0.0))
    #            for k in range(colcount):
    #                r = eval('data.tessface_vertex_colors[' + str(k) + '].data[' + str(
    #                    f.index) + '].color' + str(vert + 1) + '[0]*1023')
    #                g = eval('data.tessface_vertex_colors[' + str(k) + '].data[' + str(
    #                    f.index) + '].color' + str(vert + 1) + '[1]*1023')
    #                b = eval('data.tessface_vertex_colors[' + str(k) + '].data[' + str(
    #                    f.index) + '].color' + str(vert + 1) + '[2]*1023')
    #                eval('col_' + str(k) + '.append((r,g,b))')

        #At this point mesh is triangulated
        #I can get the triangulated input and calculate the tangents 
        tangents = calc_tangents(faces, verts, norms, luvs)
        
        #Apply rotation and normal matrices on vertices and normal vectors
        apply_local_transforms(rot_x_mat, verts, norms, tangents)
        
        return verts, norms, tangents, luvs, faces

    def parse_object(self, ob, parent):#, global_scene, process_anim = False, anim_frame_data = dict(), extra_data = dict()):
        newob = None
        #Apply location/rotation/scale
        #bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

        # get the objects' location and convert to NMS coordinates
        trans, rot_q, scale = transform_to_NMS_coords(ob)
        rot = rot_q.to_euler()
        print(trans)
        print(rot)
        print(scale)

        transform = TkTransformData(TransX=trans[0],
                                   TransY=trans[1],
                                   TransZ=trans[2],
                                   RotX=degrees(rot[0]),
                                   RotY=degrees(rot[1]),
                                   RotZ=degrees(rot[2]),
                                   ScaleX=scale[0],
                                   ScaleY=scale[1],
                                   ScaleZ=scale[2])

        entitydata = []
        
        # Main switch to identify meshes or locators/references
        if ob.type == 'MESH':
            if ob.NMSNode_props.node_types == 'Collision':
                # COLLISION MESH
                print("Collision found: ", ob.name)
                colType = ob.NMSCollision_props.collision_types
                
                optdict = {}
                optdict['Name'] = self.scene_directory
                optdict['Transform'] = transform
                optdict['CollisionType'] = colType
                
                if (colType == "Mesh"):
                    c_verts,c_norms,c_tangs,c_uvs,c_faces = self.mesh_parser(ob)
                    
                    #Reset Transforms on meshes
                    
                    optdict['Vertices'] = c_verts
                    optdict['Indexes'] = c_faces
                    optdict['UVs'] = c_uvs
                    optdict['Normals'] = c_norms
                    optdict['Tangents'] = c_tangs
                #HANDLE Primitives
                elif (colType == "Box"):
                    optdict['Width']  = ob.dimensions[0]
                    optdict['Depth']  = ob.dimensions[1]
                    optdict['Height'] = ob.dimensions[2]
                elif (colType == "Sphere"):
                    optdict['Radius'] = ob.dimensions[0] / 2.0
                elif (colType == "Cylinder"):
                    optdict['Radius'] = ob.dimensions[0] / 2.0
                    optdict['Height'] = ob.dimensions[2]
                else:
                    raise Exception("Unsupported Collision")
                
                newob = Collision(**optdict)
            elif ob.NMSNode_props.node_types == 'Mesh':
                # ACTUAL MESH
                #Parse object Geometry
                print('Exporting: ', ob.name)
                verts,norms,tangs,luvs,faces = self.mesh_parser(ob)
                print("Object Count: ", len(verts), len(luvs), len(norms), len(faces))
                print("Object Rotation: ", degrees(rot[0]), degrees(rot[2]), degrees(rot[1]))

                # check whether the mesh has any child nodes we care about (such as a rotation vector)
                for child in ob.children:
                    if child.name.upper() == 'ROTATION':
                        # take the properties of the rotation vector and give it to the mesh as part of it's entity data
                        rot = transform_to_NMS_coords(child)[1]
                        axis = Matrix.Rotation(radians(-90), 4, 'X')*(rot*Vector((0,1,0)))
                        print(axis)
                        rotation_data = TkRotationComponentData(Speed = child.empty_draw_size, Axis = Vector4f(x=axis[0],y=axis[1],z=axis[2],t=0))
                        entitydata.append(rotation_data)
                
                #Create Mesh Object
                actualname = ob.name[len("NMS_"):].upper()
                newob = Mesh(Name = actualname,
                             Transform = transform,
                             Vertices=verts,
                             UVs=luvs,
                             Normals=norms,
                             Tangents=tangs,
                             Indexes=faces,
                             ExtraEntityData = entitydata,
                             HasAttachment = ob.NMSMesh_props.has_entity)

                # check to see if the mesh's entity will be animation controller, if so assign to the anim_controller_obj variable
                if ob.NMSEntity_props.is_anim_controller:
                    self.anim_controller_obj = newob
                
                #Try to parse material
                if ob.NMSMesh_props.material_path != "":
                    newob.Material = ob.NMSMesh_props.material_path
                else:
                    try:
                        slot = ob.material_slots[0]
                        mat = slot.material
                        print(mat.name)
                        if not mat.name in self.material_dict:
                            print("Parsing Material " + mat.name)
                            material_ob = self.parse_material(ob)
                            self.material_dict[mat.name] = material_ob
                        else:
                            material_ob = self.material_dict[mat.name]
                        
                        print(material_ob)
                        #Attach material to Mesh
                        newob.Material = material_ob
                        
                    except:
                        raise Exception("Missing Material")
        
        #Locator and Reference Objects
        elif (ob.type=='EMPTY'):
            if ob.NMSNode_props.node_types == 'Reference':
                print("Reference Detected")
                actualname = ob.name[len("NMS_"):].upper()
                try:
                    scenegraph = ob.NMSReference_props.reference_path
                except:
                    raise Exception("Missing REF Property, Set it")
                
                newob = Reference(Name = actualname, Transform = transform, Scenegraph = scenegraph)
            elif ob.NMSNode_props.node_types == 'Locator':
                print("Locator Detected")
                actualname = ob.name[len("NMS_"):].upper()
                HasAttachment = ob.NMSLocator_props.has_entity
                            
                newob = Locator(Name = actualname, Transform = transform, HasAttachment = HasAttachment)
            elif ob.NMSNode_props.node_types == 'Joint':
                print("Joint Detected")
                actualname = ob.name[len("NMS_"):].upper()
                self.joints += 1
                newob = Joint(Name = actualname, Transform = transform, JointIndex = self.joints)
                
        #Light Objects
        elif (ob.type =='LAMP'):
            actualname = ob.name[len("NMS_"):].upper()      # syntax: NMS_LIGHT_<NAME>
            #Get Color
            col = tuple(ob.data.color)
            print("colour: {}".format(col))
            #Get Intensity
            intensity = ob.NMSLight_props.intensity_value
            
            newob = Light(Name=actualname, Transform = transform, Colour = col, Intensity = intensity, FOV = ob.NMSLight_props.FOV_value)
        
        parent.add_child(newob)
        
        #Parse children
        for child in ob.children:
            if not (child.name.startswith('NMS') or child.name.startswith('COLLISION')):
                continue
            child_ob = self.parse_object(child, newob)#, global_scene, process_anim, anim_frame_data, extra_data)

        return newob

    def process_anims(self):
        # get all the data. We will then consider number of actions globally and process the entity stuff accordingly
        entitydata = []
        for action in self.scene_actions:
            print("processing anim {}".format(action.name))
            # this is the current action.
            # get the list of joints that use this action
            animated_joints = []        # list of joints that use the current action
            action_data = dict()
            # get the list of joints using current action, and set their action to the current one
            for name in self.joint_anim_data:
                if action in self.joint_anim_data[name]:
                    animated_joints.append(name)
                    self.global_scene.objects[name].animation_data.action = action      # set the actions of each joint (with this action) to be the current active one
                    action_data[name] = list()
                    
            for frame in range(self.anim_frames):       # let's hope none of the anims have different amounts of frames... should be easy to fix though... later...
                # need to change the frame of the scene to appropriate one
                self.global_scene.frame_set(frame)
                # now need to re-get the data
                #print("processing frame {}".format(frame))
                for name in animated_joints:
                    ob = self.global_scene.objects[name]
                    trans, rot_q, scale = transform_to_NMS_coords(ob)
                    action_data[name].append((trans, rot_q, scale))      # this is the anim_data that will be processed later
            # add all the animation data to the anim frame data for the particular action
            self.anim_frame_data[action.name] = action_data

        # now semi-process the animation data to generate data for the animation controller entity file
        if len(self.anim_frame_data) == 1:
            # in this case we only have the idle animation.
            path = os.path.join(BASEPATH, self.group_name.upper(), self.mname.upper())
            anim_entity = TkAnimationComponentData(Idle = TkAnimationData())
            entitydata.append(anim_entity)
            self.anim_controller_obj.ExtraEntityData = entitydata      # update the entity data directly
            self.anim_controller_obj.rebuild_entity()
        elif len(self.anim_frame_data) > 1:
            # in this case all the anims are not idle ones, and we need some kind of real data
            Anims = List()
            path = os.path.join(BASEPATH, self.group_name.upper(), 'ANIMS')
            for action in self.anim_frame_data:
                name = action
                AnimationData = TkAnimationData(Anim = name,
                                                Filename = os.path.join(path, "{}.ANIM.MBIN".format(name.upper())),
                                                FlagsActive = True)
                Anims.append(AnimationData)
            anim_entity = TkAnimationComponentData(Idle = TkAnimationData(),
                                                   Anims = Anims)
            entitydata.append(anim_entity)
            self.anim_controller_obj.ExtraEntityData = entitydata      # update the entity data directly
            self.anim_controller_obj.rebuild_entity()


class NMS_Export_Operator(Operator, ExportHelper):
    """This appears in the tooltip of the operator and in the generated docs"""
    bl_idname = "export_mesh.nms"  # important since its how bpy.ops.import_test.some_data is constructed
    bl_label = "Export to NMS XML Format"

    # ExportHelper mixin class uses this
    filename_ext = ""

    def execute(self, context):
        main_exporter = Exporter(self.filepath)
        status = main_exporter.state
        self.report({'INFO'}, "Models Exported Successfully")
        if status:
            return {'FINISHED'}
        else:
            return {'CANCELLED'}


def update_after_enum(self, context):
    print('self.my_enum ---->', self.node_types)

""" Various properties for each of the different node types """

class NMSNodeProperties(bpy.types.PropertyGroup):
    """ Properties for the NMS Nodes """
    is_NMS_node = BoolProperty(name = "Is NMS Node?",
                               description = "Enable if the object is a node in the scene file",
                               default = True)
    
    node_types = EnumProperty(name = "Node Types",
                              description = "Select what type of Node this will be",
                              items = [("Mesh" , "Mesh" , "Standard mesh for visible objects."),
                                       ("Collision", "Collision", "Shape of collision for object."),
                                       ("Locator", "Locator", "Locator object, used for interaction locations etc."),
                                       ("Reference", "Reference", "Node used to allow other scenes to be placed at this point in space"),
                                       ("Joint", "Joint", "Node used primarily for animations. All meshes that are to be animated MUST be a direct child of a joint object"),
                                       ("Light", "Light", "Light that will emit light of a certain colour")],
                              update=update_after_enum)

class NMSMeshProperties(bpy.types.PropertyGroup):
    has_entity = BoolProperty(name = "Requires Entity",
                              description = "Whether or not the mesh requires an entity file. Not all meshes require an entity file. Read the detailed guidelines in the readme for more details.",
                              default = False)
    material_path = StringProperty(name = "Material",
                                   description = "(Optional) Path to material mbin file to use instead of automattical exporting material attached to this mesh.")

class NMSLightProperties(bpy.types.PropertyGroup):
    intensity_value = FloatProperty(name = "Intensity",
                                    description = "Intensity of the light.")
    FOV_value = FloatProperty(name = "FOV",
                              description = "Field if View of the lightsource.",
                              default = 360,
                              min = 0,
                              max = 360)

class NMSEntityProperties(bpy.types.PropertyGroup):
    is_anim_controller = BoolProperty(name = "Is animation controller?",
                                      description = "When ticked, this entity contains all the required animation information. Only tick this for one entity per scene.",
                                      default = False)
    is_flyable = BoolProperty(name = "Is flyable?",
                              description = "If true, the entity file will contain the required components to make the object pilotable.",
                              default = False)

class NMSAnimationProperties(bpy.types.PropertyGroup):
    anim_loops = BoolProperty(name = "Loops",
                              description = "If true, the the animation will loop.",
                              default = False)
    anim_loops_choice = EnumProperty(name = "Animation Type",
                                   description = "Type of animation",
                                   items = [("OneShot" , "OneShot" , "Animation runs once (per trigger)"),
                                            ("Loop", "Loop", "Animation loops continuously")])

class NMSLocatorProperties(bpy.types.PropertyGroup):
    has_entity = BoolProperty(name = "Requires Entity",
                              description = "Whether or not the mesh requires an entity file. Not all meshes require an entity file. Read the detailed guidelines in the readme for more details.",
                              default = False)

class NMSReferenceProperties(bpy.types.PropertyGroup):
    reference_path = StringProperty(name = "Reference Path",
                                    description = "Path to scene to be referenced at this location.")

class NMSSceneProperties(bpy.types.PropertyGroup):
    batch_mode = BoolProperty(name = "Batch Mode",
                              description = "If ticked, each direct child of this node will be exported separately",
                              default = False)
    group_name = StringProperty(name = "Group Name",
                                description = "Group name so that models that all belong in the same folder are placed there (path becomes group_name/name)")
    dont_compile = BoolProperty(name = "Don't compile to .mbin",
                                description = "If true, the exml files will not be compiled to an mbin file. This saves a lot of time waiting for the geometry files to compile",
                                default = False)

class NMSCollisionProperties(bpy.types.PropertyGroup):
    collision_types = EnumProperty(name = "Collision Types",
                                   description = "Type of collision to be used",
                                   items = [("Mesh" , "Mesh" , "Mesh Collision"),
                                            ("Box", "Box", "Box (rectangular prism collision"),
                                            ("Sphere", "Sphere", "Spherical collision"),
                                            ("Cylinder", "Cylinder", "Cylindrical collision")])

""" Various panels for each of the property types """

class NMSNodePropertyPanel(bpy.types.Panel):
    """Creates a Panel in the scene context of the properties editor"""
    bl_label = "NMS Node Properties"
    bl_idname = "OBJECT_PT_node_properties"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        if context.object.name.startswith("NMS") and not context.object.name.startswith("NMS_SCENE"):
            return True
        else:
            return False

    def draw(self, context):
        layout = self.layout
        obj = context.object
        row = layout.row()
        row.prop(obj.NMSNode_props, "node_types", expand=True)

class NMSReferencePropertyPanel(bpy.types.Panel):
    """Creates a Panel in the scene context of the properties editor"""
    bl_label = "NMS Reference Properties"
    bl_idname = "OBJECT_PT_reference_properties"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        if context.object.name.startswith("NMS") and context.object.NMSNode_props.node_types == 'Reference':
            return True
        else:
            return False

    def draw(self, context):
        layout = self.layout
        obj = context.object
        row = layout.row()
        row.prop(obj.NMSReference_props, "reference_path")

class NMSMeshPropertyPanel(bpy.types.Panel):
    """Creates a Panel in the scene context of the properties editor"""
    bl_label = "NMS Mesh Properties"
    bl_idname = "OBJECT_PT_mesh_properties"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        if context.object.name.startswith("NMS") and context.object.NMSNode_props.node_types == 'Mesh' and not context.object.name.startswith("NMS_SCENE"):
            return True
        else:
            return False

    def draw(self, context):
        layout = self.layout
        obj = context.object
        row = layout.row()
        row.prop(obj.NMSMesh_props, "has_entity")
        row = layout.row()
        row.prop(obj.NMSMesh_props, "material_path")

class NMSEntityPropertyPanel(bpy.types.Panel):
    """Creates a Panel in the scene context of the properties editor"""
    bl_label = "NMS Entity Properties"
    bl_idname = "OBJECT_PT_entity_properties"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        if context.object.name.startswith("NMS") and (context.object.NMSMesh_props.has_entity or context.object.NMSLocator_props.has_entity):
            # only a mesh or locator can have an associated entity file
            return True
        else:
            return False

    def draw(self, context):
        layout = self.layout
        obj = context.object
        row = layout.row()
        row.prop(obj.NMSEntity_props, "is_anim_controller")
        row = layout.row()
        row.prop(obj.NMSEntity_props, "is_flyable")

class NMSAnimationPropertyPanel(bpy.types.Panel):
    """Creates a Panel in the scene context of the properties editor"""
    bl_label = "NMS Animation Properties"
    bl_idname = "OBJECT_PT_animation_properties"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        if context.object.name.startswith("NMS") and context.object.NMSNode_props.node_types == 'Mesh':     # fix
            return True
        else:
            return False

    def draw(self, context):
        layout = self.layout
        obj = context.object
        row = layout.row()
        row.prop(obj.NMSAnimation_props, "anim_loops")
        row = layout.row()
        row.prop(obj.NMSAnimation_props, "anim_loops_choice", expand = True)

class NMSLocatorPropertyPanel(bpy.types.Panel):
    """Creates a Panel in the scene context of the properties editor"""
    bl_label = "NMS Locator Properties"
    bl_idname = "OBJECT_PT_locator_properties"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        if context.object.name.startswith("NMS") and context.object.NMSNode_props.node_types == 'Locator':
            return True
        else:
            return False

    def draw(self, context):
        layout = self.layout
        obj = context.object
        row = layout.row()
        row.prop(obj.NMSLocator_props, "has_entity")

class NMSLightPropertyPanel(bpy.types.Panel):
    """Creates a Panel in the scene context of the properties editor"""
    bl_label = "NMS Light Properties"
    bl_idname = "OBJECT_PT_light_properties"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        if context.object.name.startswith("NMS") and context.object.NMSNode_props.node_types == 'Light':
            return True
        else:
            return False

    def draw(self, context):
        layout = self.layout
        obj = context.object
        row = layout.row()
        row.prop(obj.NMSLight_props, "intensity_value")
        row = layout.row()
        row.prop(obj.NMSLight_props, "FOV_value")

class NMSCollisionPropertyPanel(bpy.types.Panel):
    """Creates a Panel in the scene context of the properties editor"""
    bl_label = "NMS Collision Properties"
    bl_idname = "OBJECT_PT_collision_properties"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        if context.object.name.startswith("NMS") and context.object.NMSNode_props.node_types == 'Collision':
            return True
        else:
            return False

    def draw(self, context):
        layout = self.layout
        obj = context.object
        row = layout.row()
        row.prop(obj.NMSCollision_props, "collision_types", expand=True)

class NMSScenePropertyPanel(bpy.types.Panel):
    """Creates a Panel in the scene context of the properties editor"""
    bl_label = "NMS Scene Properties"
    bl_idname = "OBJECT_PT_scene_properties"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        # this should only show for an object that is called NMS_SCENE
        if context.object.name.startswith("NMS_SCENE"):
            return True
        else:
            return False

    def draw(self, context):
        layout = self.layout
        obj = context.object
        row = layout.row()
        row.prop(obj.NMSScene_props, "batch_mode")
        row = layout.row()
        row.prop(obj.NMSScene_props, "group_name", expand = True)
        row = layout.row()
        row.prop(obj.NMSScene_props, "dont_compile")


# Only needed if you want to add into a dynamic menu
def menu_func_export(self, context):
    self.layout.operator(NMS_Export_Operator.bl_idname, text="Export to NMS XML Format ")

def register():
    bpy.utils.register_class(NMS_Export_Operator)
    bpy.types.INFO_MT_file_export.append(menu_func_export)
    # register the properties
    bpy.utils.register_class(NMSNodeProperties)
    bpy.utils.register_class(NMSSceneProperties)
    bpy.utils.register_class(NMSMeshProperties)
    bpy.utils.register_class(NMSReferenceProperties)
    bpy.utils.register_class(NMSLocatorProperties)
    bpy.utils.register_class(NMSLightProperties)
    bpy.utils.register_class(NMSEntityProperties)
    #bpy.utils.register_class(NMSAnimationProperties)
    bpy.utils.register_class(NMSCollisionProperties)
    # link the properties with the objects' internal variables
    bpy.types.Object.NMSNode_props = bpy.props.PointerProperty(type=NMSNodeProperties)
    bpy.types.Object.NMSScene_props = bpy.props.PointerProperty(type=NMSSceneProperties)
    bpy.types.Object.NMSMesh_props = bpy.props.PointerProperty(type=NMSMeshProperties)
    bpy.types.Object.NMSReference_props = bpy.props.PointerProperty(type=NMSReferenceProperties)
    bpy.types.Object.NMSLocator_props = bpy.props.PointerProperty(type=NMSLocatorProperties)
    bpy.types.Object.NMSLight_props = bpy.props.PointerProperty(type=NMSLightProperties)
    bpy.types.Object.NMSEntity_props = bpy.props.PointerProperty(type=NMSEntityProperties)
    #bpy.types.Object.NMSAnimation_props = bpy.props.PointerProperty(type=NMSAnimationProperties)
    bpy.types.Object.NMSCollision_props = bpy.props.PointerProperty(type=NMSCollisionProperties)
    # register the panels
    bpy.utils.register_class(NMSScenePropertyPanel)
    bpy.utils.register_class(NMSNodePropertyPanel)
    bpy.utils.register_class(NMSMeshPropertyPanel)
    bpy.utils.register_class(NMSReferencePropertyPanel)
    bpy.utils.register_class(NMSLocatorPropertyPanel)
    bpy.utils.register_class(NMSLightPropertyPanel)
    bpy.utils.register_class(NMSEntityPropertyPanel)
    #bpy.utils.register_class(NMSAnimationPropertyPanel)
    bpy.utils.register_class(NMSCollisionPropertyPanel)


def unregister():
    bpy.utils.unregister_class(NMS_Export_Operator)
    bpy.types.INFO_MT_file_export.remove(menu_func_export)
    # unregister the property classes
    bpy.utils.unregister_class(NMSNodeProperties)
    bpy.utils.unregister_class(NMSSceneProperties)
    bpy.utils.unregister_class(NMSMeshProperties)
    bpy.utils.unregister_class(NMSReferenceProperties)
    bpy.utils.unregister_class(NMSLocatorProperties)
    bpy.utils.unregister_class(NMSLightProperties)
    bpy.utils.unregister_class(NMSEntityProperties)
    #bpy.utils.unregister_class(NMSAnimationProperties)
    bpy.utils.unregister_class(NMSCollisionProperties)
    # delete the properties from the objects
    del bpy.types.Object.NMSNode_props
    del bpy.types.Object.NMSScene_props
    del bpy.types.Object.NMSMesh_props
    del bpy.types.Object.NMSReference_props
    del bpy.types.Object.NMSLocator_props
    del bpy.types.Object.NMSLight_props
    del bpy.types.Object.NMSEntity_props
    #del bpy.types.Object.NMSAnimation_props
    del bpy.types.Object.NMSCollision_props
    # unregister the panels
    bpy.utils.unregister_class(NMSScenePropertyPanel)
    bpy.utils.unregister_class(NMSNodePropertyPanel)
    bpy.utils.unregister_class(NMSMeshPropertyPanel)
    bpy.utils.unregister_class(NMSReferencePropertyPanel)
    bpy.utils.unregister_class(NMSLocatorPropertyPanel)
    bpy.utils.unregister_class(NMSLightPropertyPanel)
    bpy.utils.unregister_class(NMSEntityPropertyPanel)
    #bpy.utils.unregister_class(NMSAnimationPropertyPanel)
    bpy.utils.unregister_class(NMSCollisionPropertyPanel)


if __name__ == "__main__":
    register()

    # test call
    bpy.ops.export_mesh.nms(filepath="J:\\Installs\\Steam\\steamapps\\common\\No Man's Sky\\GAMEDATA\\PCBANKS\\CONSTRUCTRAMP")
