import newGameLib
reload(newGameLib)
from newGameLib import *
import Blender	



def pamParser(filename,g):
	if 'object'+os.sep in filename:
		texDir=filename.split('object')[0]+'object'+os.sep+'texture'
	else:
		texDir=g.dirname
	#g.debug=True
	idMagic = g.word(4); parVer = g.H(1)[0]
	g.seek(0x10)
	if parVer == 1286:
		meshList=[]
		meshCount=g.i(1)[0]
		g.f(6)
		g.B(10)
		g.seek(1040)
		for m in range(meshCount):
			mesh=Mesh()
			mat=Mat()
			mat.TRIANGLE=True
			t=g.tell()
			mesh.info=g.i(5)
			mat.diffuse=texDir+os.sep+g.find('\x00')
			g.seek(t+276)
			mesh.matList.append(mat)
			meshList.append(mesh)
		for i,mesh in enumerate(meshList):
			for m in range(mesh.info[0]):
				t=g.tell()
				mesh.vertPosList.append(g.f(3))
				g.seek(t+16)
				mesh.vertUVList.append(g.half(2))
				g.seek(t+28)
		for i,mesh in enumerate(meshList):
			mesh.indiceList=g.H(mesh.info[1])
			mesh.draw()	
	elif parVer == 1030:
		meshList=[]
		meshCount=g.i(1)[0]
		g.f(6)
		g.B(10)
		g.seek(1040)
		for m in range(meshCount):
			mesh=Mesh()
			mat=Mat()
			mat.TRIANGLE=True
			t=g.tell()
			mesh.info=g.i(4)
			mat.diffuse=texDir+os.sep+g.find('\x00')
			g.seek(t+272)
			mesh.matList.append(mat)
			meshList.append(mesh)
		for i,mesh in enumerate(meshList):
			for m in range(mesh.info[0]):
				t=g.tell()
				mesh.vertPosList.append(g.f(3))
				g.seek(t+16)
				mesh.vertUVList.append(g.half(2))
				g.seek(t+28)
		for i,mesh in enumerate(meshList):
			mesh.indiceList=g.H(mesh.info[1])
			mesh.draw()	
	else:
		print 'WARNING:unknow version:',parVer
			
	#g.debug=True
	#g.tell()
			
def Parser():
	filename=input.filename
	ext=filename.split('.')[-1].lower()
	
	if ext=='pam':
		file=open(filename,'rb')
		g=BinaryReader(file)
		pamParser(filename,g)
		file.close()
	
 
def openFile(flagList):
	global input,output
	input=Input(flagList)
	output=Output(flagList)
	parser=Parser()
	
Blender.Window.FileSelector(openFile,'import','Black Desert Online files: *.pam') 