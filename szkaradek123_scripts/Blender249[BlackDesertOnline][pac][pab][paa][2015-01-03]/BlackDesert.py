import newGameLib
reload(newGameLib)
from newGameLib import *
import Blender	

def pacParser(filename,g):
	idMagic = g.i(1)[0]; parVer = g.H(1)[0]
	g.seek(0x10)
	if parVer == 259:
		boneCount     = g.B(1)[0]
		bonehashList=[]
		for m in range(boneCount):bonehashList.append(g.i(1)[0])
		usedBoneCount = g.B(1)[0]
		usedBones     = g.B(usedBoneCount)
		totalVert, totalFace,  = g.i(2)
		meshCount=g.H(1)[0]
		for a in range(0, meshCount):
			meshNameSize = g.B(1)[0]
			meshName = g.word(meshNameSize)
			print meshName
			flag = g.H(1)[0]
			material = Mat()
			material.TRIANGLE=True
			material.ZTRANS=True
			texture_path=g.dirname.split('model')[0]+os.sep+'texture'+os.sep
			material.diffuse=texture_path+meshName+'.dds'
			material.specular=texture_path+meshName+'_sp.dds'
			#material.normal=texture_path+meshName+'_n.dds'
			mesh=Mesh()
			for b in range(0, 3):
				vertCount = g.H(1)[0]
				skin=Skin()
				for m in range(vertCount):
					t=g.tell()
					mesh.vertPosList.append(g.f(3))
					g.seek(t+16)
					mesh.vertUVList.append(g.half(2))
					g.seek(t+24)
					mesh.skinIndiceList.append(g.B(4))
					mesh.skinWeightList.append(g.B(4))
					g.seek(t+0x20)
				faceCount = g.i(1)[0]
				mesh.indiceList=g.H(faceCount)
				skin.boneMap=bonehashList
				if b < 1:
					mesh.TRIANGLE=True
					mesh.matList.append(material)
					mesh.skinList.append(skin)
					mesh.BINDSKELETON='armature'
					mesh.draw()	

def pabParser(filename,g):	
	g.word(4)
	parVer = g.H(1)[0]
	g.seek(0x10)	
	skeleton=Skeleton()
	skeleton.ARMATURESPACE=True
	skeleton.BINDMESH=True
	g.seek(16)
	boneCount = g.H(1)[0]
	for m in range(0, boneCount):
		bone=Bone()
		bone.name = str(g.i(1)[0])
		name=g.word(g.B(1)[0])
		bone.parentID = g.i(1)[0]
		bone.matrix=Matrix4x4(g.f(16))
		g.seek(64,1)
		g.seek(64,1)
		g.seek(64,1)
		boneScale = g.f(3)
		BoneQuat  = g.f(4)
		BonePos   = g.f(3)
		g.seek(0x2,1)
		skeleton.boneList.append(bone)
	skeleton.draw()	
	
		
def paaParser(filename,g):
	action=Action()
	action.BONESPACE=True
	action.BONESORT=True
	action.skeleton='armature'
	g.word(4)
	g.seek(16)
	boneCount=g.H(1)[0]
	g.H(4)
	for m in range(boneCount):
		g.logWrite('key'+str(m))
		bone=ActionBone()
		bone.name=str(g.i(1)[0])	
		c1=g.H(1)[0]
		for n in range(c1):#scale key
			g.H(4)
		c2=g.H(1)[0]
		for n in range(c2):#rotation key
			bone.rotFrameList.append(g.H(1)[0]/33)
			bone.rotKeyList.append(QuatMatrix(g.half(4)).resize4x4())	
			
		c3=g.H(1)[0]
		for n in range(c3):#transaltion key
			bone.posFrameList.append(g.H(1)[0]/33)
			bone.posKeyList.append(VectorMatrix(g.half(3)))	
		action.boneList.append(bone)	
	action.draw()
	action.setContext()	
		
	
			
def Parser():
	filename=input.filename
	ext=filename.split('.')[-1].lower()	
	
	if ext=='pac':
		file=open(filename,'rb')
		g=BinaryReader(file)
		pacParser(filename,g)
		file.close()
	
	if ext=='pab':
		file=open(filename,'rb')
		g=BinaryReader(file)
		pabParser(filename,g)
		file.close()
	
	if ext=='paa':
		file=open(filename,'rb')
		g=BinaryReader(file)
		paaParser(filename,g)
		file.close()
	
 
def openFile(flagList):
	global input,output
	input=Input(flagList)
	output=Output(flagList)
	parser=Parser()
	
Blender.Window.FileSelector(openFile,'import','Black Desert Online files: pac-mesh, pab-skeleton, paa-animation ') 