import os
os.sys.path.append('../')
import torch
import os.path as osp
import numpy as np
import torch
import torchvision
import pickle
from PIL import Image
from module.SkinWeightModel import SkinWeightNet
import module.ImageReconstructModel as M
from glob import glob
import argparse
import cv2

def save_batch_pickles(bps, names, trans=None):
	if trans is None:
		trans = [[0, 0, 0] for _ in range(len(names))]
	width = 1080
	height = 1080
	camera_c = [540.0, 540.0]
	camera_f = [1080, 1080]
	num = 1

	for i, (bp, name) in enumerate(zip(bps, names)):
		bp = bp * [1, -1, -1] + trans[i]
		vertices = bp[None,:].repeat(num, axis=0)
		data_to_save = {'width': width, 'camera_c': camera_c, 'vertices': vertices,
						'camera_f': camera_f, 'height': height}
		pickle_out = open('{}'.format(name), "wb")
		pickle.dump(data_to_save, pickle_out)
		pickle_out.close()

def save_obj(ps,tris,name, with_uv, trans):
	with open(name, 'w') as fp:
		base_name = os.path.basename(name).split('.')[0]
		if with_uv:
			with open('../obj_info.txt', 'r') as f_info:
				info = f_info.readlines()
			with open('../mtl_info.txt', 'r') as m_info:
				mtl_info = m_info.readlines()
			with open(name.replace('.obj', '.mtl'), 'w') as fm:
				fm.write(''.join(mtl_info))
				fm.write('map_Kd %s_octopus.jpg' % (base_name))
			fp.write('mtlib %s.mtl\n' % (base_name))
		for v in ps:
			fp.write('v {:f} {:f} {:f}\n'.format(v[0] + trans[0], -v[1] + trans[1], -v[2] + trans[2]))
		if tris is not None:
			if not with_uv:
				for f in tris: # Faces are 1-based, not 0-based in obj files
					fp.write( 'f {:d} {:d} {:d}\n'.format(f[0] + 1, f[1] + 1, f[2] + 1) )
			else:
				fp.write(''.join(info))
				fp.write('\nusemtl Mymtl')

def save_batch_objs(bps,face_index,batch,names, with_uv=False, trans=None):
	if trans is None:
		trans = [[0, 0, 0] for _ in range(len(names))]
	if len(bps.shape)==2:
		assert(len(names)==batch.max()+1)
		voffset=0
		for ind in range(len(names)):
			select=batch==ind
			vnum=select.sum()
			tris=face_index[(face_index>=voffset) * (face_index<voffset+vnum)].reshape(-1,3)-voffset
			ps=bps[select]
			save_obj(ps,tris,names[ind], with_uv=with_uv, trans=trans[ind])
			voffset+=vnum
	elif len(bps.shape)==3:
		assert(bps.shape[0]==len(names))
		for ind, (ps,n) in enumerate(zip(bps,names)):
			save_obj(ps,face_index,n, with_uv=with_uv, trans=trans[ind])
	else:
		assert(False)
def cal_linear_model(seg_info_list, obj_info_list):
	results = []
	for seg_info, obj_info in zip(seg_info_list,obj_info_list):
		min_value = seg_info['min_value']
		h = seg_info['h']
		max_value_obj = obj_info['max_value_obj']
		h_obj = obj_info['h_obj']

		X = h_obj/float(h)
		#z_trans = -790.5653053 * X -0.59800634
		z_trans = -1097.2751867681575 * X
		#y = 1.26410603 * X - 0.000465135  # y = (max_value_obj) / float(540 - min_value)
		y = X
		max_value_obj_pred = y * (540 - min_value)
		y_trans = max_value_obj_pred - max_value_obj
		results.append([0, y_trans.item(), z_trans.item()])
	return results

def read_img(file):
	img=cv2.imread(file)
	h=img.shape[0]
	w=img.shape[1]
	if h!=w:
		l=max(h,w)
		nimg=np.zeros((l,l,3),np.uint8)
		hs=max(int((l-h)/2.),0)
		he=min(int((l+h)/2.),l)
		he=min(he,hs+h)
		ws=max(int((l-w)/2.),0)
		we=min(int((l+w)/2.),l)
		we=min(we,ws+w)
		nimg[hs:he,ws:we]=img[:he-hs,:we-ws]
	else:
		nimg=img
	nimg=cv2.resize(nimg,(540,540))
	nimg=nimg.transpose(2,0,1)
	nimg=nimg.astype(np.float32)/255.
	return nimg

def read_seg(file):
	toTensor = torchvision.transforms.ToTensor()
	a = Image.open(file)
	min_value = torch.where(toTensor(a).permute(1, 2, 0).sum(2) > 0)[0].min()
	max_value = torch.where(toTensor(a).permute(1, 2, 0).sum(2) > 0)[0].max()
	return {'file' : file, 'min_value' : min_value, 'max_value' : max_value, 'h' : max_value - min_value}

parser = argparse.ArgumentParser(description='img rec comparing')
parser.add_argument('--gpu-id',default=0,type=int,metavar='ID',
                    help='gpu id')
parser.add_argument('--inputs',default=None,metavar='M',
                    help='read inputs')
parser.add_argument('--trans', default='base',
                    help='[base, octopus, linear]')

args = parser.parse_args()
inputs=osp.join(args.inputs, 'frames')
img_files=[]
img_gtypes=[]
if osp.isdir(inputs):
	img_files.extend(glob(osp.join(inputs,'*_0.jpg')))
	img_files.extend(glob(osp.join(inputs,'*_0.png')))
	for imf in img_files:
		temp=imf[:-4]+'_gtypes.txt'
		if osp.isfile(temp):
			with open(temp,'r') as ff:
				img_gtypes.append([int(v) for v in ff.read().split()])
		else:
			img_gtypes.append([-1,-1])
elif osp.isfile(inputs):
	with open(inputs,'r') as ff:
		temp=ff.read().split('\n')				
		for line in temp:
			line=line.split()
			if len(line)>0:
				img_files.append(line[0])
			temp=[]
			if len(line)>1 and line[1].isdigit():
				temp.append(int(line[1]))
			else:
				temp.append(-1)
			if len(line)>2 and line[2].isdigit():
				temp.append(int(line[2]))
			else:
				temp.append(-1)
			img_gtypes.append(temp)

if len(img_files)==0:
	print('zeros img files, exit.')
	exit()


save_root=args.inputs
if not osp.isdir(save_root):
	os.makedirs(save_root)
batch_size=20
if args.gpu_id==None:
	device=torch.device('cpu')
else:
	device=torch.device(args.gpu_id)

skinWsNet=SkinWeightNet(4,True)
net=M.ImageReconstructModel(skinWsNet,True)
net.load_state_dict(torch.load('../models/garNet.pth',map_location='cpu'),True)
net=net.to(device)
net.eval()

# img_files=glob('MGN_datas/*.jpg')
batch_num=len(img_files)//batch_size
if batch_num*batch_size<len(img_files):
	batch_num+=1
# save_num=20
dis_ablation=False
print('total %d imgfiles'%len(img_files))
with torch.no_grad():	
	for batch_id in range(0,batch_num):
		s_id=batch_id*batch_size
		e_id=s_id+batch_size
		if e_id>len(img_files):
			e_id=len(img_files)
		batch_files=img_files[s_id:e_id]
		imgs=[]
		for file in batch_files:
			imgs.append(read_img(file))
		if args.trans == 'linear':
			seg_info = []
			for file in batch_files:
				seg_info.append(read_seg(file.replace('frames', 'segmentations').replace('jpg','png')))
		imgs=torch.from_numpy(np.stack(imgs,axis=0)).to(device)
		gps_pca,gps_diss,gps_rec,ws,shape_rec,pose_rec,tran_rec,pca_perg,displacement,body_js,body_ns,body_ps,_,_, pose_Rs=\
			net(imgs,gtypes=img_gtypes[s_id:e_id])
		if args.trans == 'linear':
			obj_info = []
			for i in range(len(seg_info)):
				obj_info.append({'min_value_obj' : body_ps[i:i+1 ,:,1].min(dim=1).values, 'max_value_obj' : body_ps[i:i+1,:,1].max(dim=1).values,
								 'h_obj' : body_ps[i:i+1,:,1].max(dim=1).values - body_ps[i:i+1,:,1].min(dim=1).values})

		face_index=net.face_index.cpu().numpy()
		garbatch=net.garbatch.cpu().numpy()
		names=[]
		names_body=[]
		names_pickle=[]
		for ind,file in enumerate(batch_files):
			basename=osp.splitext(osp.basename(file))[0]
			os.makedirs(osp.join(save_root), exist_ok=True)
			names.append(osp.join(save_root, f'{basename}_up.obj'))
			names.append(osp.join(save_root, f'{basename}_bottom.obj'))
			names_body.append(osp.join(save_root, f'{basename}.obj'))
			names_pickle.append(osp.join(save_root, 'frame_data.pkl'))

		if args.trans == 'base':
			trans = [[0, 0, 0], [0, 0, 0], [0, 0, 0], [0, 0, 0], [0, 0, 0], [0, 0, 0]]
		elif args.trans == 'octopus':
			trans = pickle.load(open(osp.join(args.inputs,'octopus_trans.pkl'), 'rb'))

		elif args.trans == 'linear':
			trans = cal_linear_model(seg_info, obj_info)
			trans = [[t[0], t[1] + 0.09, t[2]] for t in trans]

		trans_init = [-0.01419546, -0.49839815, 0.03960332]

		trans = [[t[0] + trans_init[0],t[1] + trans_init[1], t[2] + trans_init[2]] for t in trans]
		trans_gar = [trans[i//2] for i in range(len(trans)*2)]

		save_batch_objs(gps_rec.cpu().numpy(),face_index,garbatch,names, trans=trans_gar)
		save_batch_objs(body_ps.cpu().numpy(),net.smpl.faces,None,[name.replace('.obj','_ori.obj') for name in names_body], trans=trans) #body_ps -> [B, 6890, 3] net.smpl.faces -> 13776,3
		save_batch_objs(body_ps.cpu().numpy(),net.smpl.faces,None,names_body, with_uv=True, trans=trans)
		save_batch_pickles(body_ps.cpu().numpy(), names_pickle, trans=trans)


		SMPL_parameter = {'shape': shape_rec.cpu().numpy(), 'pose': pose_Rs.cpu().numpy()}
		pickle_out = open('{}'.format(os.path.join(save_root, 'SMPL_parameter.pkl')), "wb")
		pickle.dump(SMPL_parameter, pickle_out)
		pickle_out.close()
		print(batch_id)


print('done.')
