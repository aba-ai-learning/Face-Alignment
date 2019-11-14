#-*- coding: utf-8 -*-
import os
import random as rd
import numpy as np
import cv2
import shutil
import sys
sys.path.append(os.path.abspath(os.path.join(os.getcwd(), "../../")))# 终端运行时的位置偏移
# from Utils.utils import calculate_pitch_yaw_roll
debug = False

# 绕center旋转，输出旋转后的landmark和变换矩阵，M这个矩阵怎么来的PPT有介绍
def rotate(angle, center, landmark):
    # 角度转弧度
    rad = angle * np.pi / 180.0
    alpha = np.cos(rad)
    beta = np.sin(rad)
    M = np.zeros((2,3), dtype=np.float32)
    M[0, 0] = alpha
    M[0, 1] = beta
    M[0, 2] = (1-alpha)*center[0] - beta*center[1]
    M[1, 0] = -beta
    M[1, 1] = alpha
    M[1, 2] = beta*center[0] + (1-alpha)*center[1]

    landmark_ = np.asarray([(M[0,0]*x+M[0,1]*y+M[0,2],
                             M[1,0]*x+M[1,1]*y+M[1,2]) for (x,y) in landmark])
    return M, landmark_

class ImageDate():
    def __init__(self, line, image_size=224):
        # 设定图像大小
        self.image_size = image_size
        # 拆分一行label信息分析
        line = line.strip().split()
        #0: 图片路径  1-4: bbox 坐标点;
        #5-46: landmark
        assert(len(line) == 47)
        self.list = line
        # 将landmark关键点坐标转成n个点[[x0,y0],[x1,y1],...]
        self.landmark = np.asarray(list(map(float, line[5:])), dtype=np.float32).reshape(-1, 2)
        # bbox坐标点
        self.box = np.asarray(list(map(int, map(float, line[1:5]))),dtype=np.int32)
        self.path = line[0]        # 图片路径
        self.img = None        # 图片数据
        self.imgs = []        # 图片数据集
        self.landmarks = []        # 关键点数据集

    def load_data(self, is_train, repeat, mirror=None):
        # 判断是否需要对其进行镜像处理的图像增强操作
        if (mirror is not None):
            # 读取镜像后坐标点排列的文件，只有一行数
            with open(mirror, 'r') as f:
                lines = f.readlines()
                assert len(lines) == 1
                mirror_idx = lines[0].strip().split(',')
                # 保存landmarks镜像后坐标点的序列
                mirror_idx = list(map(int, mirror_idx))
        # 求原始坐标的最小值（原始最左下角）
        xy = np.min(self.landmark, axis=0).astype(np.int32)
        # 求原始坐标的最大值（原始最右上角）
        zz = np.max(self.landmark, axis=0).astype(np.int32)
        # 求landmark的宽度和高度
        wh = zz - xy + 1
        # 求landmark的中心点(center_x,center_y)
        center = (xy + wh/2).astype(np.int32)
        img = cv2.imread(self.path)
        # 扩大ROI 0.2倍(以最长的边 * 1.2作为boxsize)
        boxsize = int(np.max(wh)*1.2)
        # 求取扩展后的最左上点
        xy = center - boxsize//2
        # 扩展后最左上点
        x1, y1 = xy
        # 扩展后最右下点
        x2, y2 = xy + boxsize
        # 获取图像长宽
        height, width, _ = img.shape
        # 判断是否超出原始图像
        dx = max(0, -x1)
        dy = max(0, -y1)
        # 避免坐标出现负值
        x1 = max(0, x1)
        y1 = max(0, y1)
        # 判断是否超出原始图像
        edx = max(0, x2 - width)
        edy = max(0, y2 - height)
        # 限制bbox不超过原图
        x2 = min(width, x2)
        y2 = min(height, y2)
        # 不会超出原图（截取bbox的图像数据）
        imgT = img[y1:y2, x1:x2]
        # 若超出原始图像就需要对bbox截取的图片进行填充，cv2.BORDER_CONSTANT，扩展区域填充0
        if (dx > 0 or dy > 0 or edx > 0 or edy > 0):
            imgT = cv2.copyMakeBorder(imgT, dy, edy, dx, edx, cv2.BORDER_CONSTANT, 0)
        # 特殊情况：landmark的跨度，宽度为0，或者长度为0的情况（观察）：
        if imgT.shape[0] == 0 or imgT.shape[1] == 0:
            imgTT = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            for x, y in (self.landmark+0.5).astype(np.int32):
                cv2.circle(imgTT, (x, y), 1, (0, 0, 255))
            cv2.imshow('0', imgTT)
            if cv2.waitKey(0) == 27:
                exit()
        # 将图片resize到image_size=112，默认112，形状一定要正方形，这个跟landmark有关
        imgT = cv2.resize(imgT, (self.image_size, self.image_size))
        # 将关键点坐标归一化，bbox为正方形
        landmark = (self.landmark - xy)/boxsize
        # 检查坐标点数据是否满足0<= x,y <= 1
        assert (landmark >= 0).all(), str(landmark) + str([dx, dy])
        assert (landmark <= 1).all(), str(landmark) + str([dx, dy])
        # 添加到图片数据集
        self.imgs.append(imgT)
        # 添加到关键点数据集
        self.landmarks.append(landmark)

        if is_train:
            while len(self.imgs) < repeat:
                # 绕随机中心点做随机旋转(-30,30)
                angle = np.random.randint(-30, 30)
                # 上面已经计算了人脸框的中心点
                cx, cy = center
                # 将中心点随机偏移，作为图像的旋转中心
                cx = cx + int(np.random.randint(-boxsize*0.1, boxsize*0.1))
                cy = cy + int(np.random.randint(-boxsize * 0.1, boxsize * 0.1))
                # 计算变换矩阵和返回变换后的landmarks
                M, landmark = rotate(angle, (cx,cy), self.landmark)
                # 将图片按照变换矩阵进行仿射变换 输入图像,M: 变换矩阵,dsize:输出图像的大小
                imgT = cv2.warpAffine(img, M, (int(img.shape[1]*1.1), int(img.shape[0]*1.1)))

                # np.ptp(axis=0)是同一列中不同列的最大值和最小值的差值，求得新宽度和高度
                wh = np.ptp(landmark, axis=0).astype(np.int32) + 1
                # np.ceil向上取整, 运算称为Ceiling，扩展1.25倍，然后随机选取
                size = np.random.randint(int(np.min(wh)), np.ceil(np.max(wh) * 1.25))
                # 计算新的左上角坐标
                xy = np.asarray((cx - size // 2, cy - size//2), dtype=np.int32)
                # 归一化坐标点
                landmark = (landmark - xy) / size
                # 检查比例情况，因为这里有随机过程，如果比例不对就重新算
                if (landmark < 0).any() or (landmark > 1).any():
                    continue

                x1, y1 = xy
                x2, y2 = xy + size
                height, width, _ = imgT.shape
                dx = max(0, -x1)
                dy = max(0, -y1)
                x1 = max(0, x1)
                y1 = max(0, y1)

                edx = max(0, x2 - width)
                edy = max(0, y2 - height)
                x2 = min(width, x2)
                y2 = min(height, y2)

                imgT = imgT[y1:y2, x1:x2]
                if (dx > 0 or dy > 0 or edx >0 or edy > 0):
                    imgT = cv2.copyMakeBorder(imgT, dy, edy, dx, edx, cv2.BORDER_CONSTANT, 0)
                # resize 112 X 112
                imgT = cv2.resize(imgT, (self.image_size, self.image_size))
                # 随机水平翻转
                if mirror is not None and np.random.choice((True, False)):
                    # 关键点坐标水平翻转
                    landmark[:,0] = 1 - landmark[:,0]
                    # mirror_idx 镜像后的坐标排列，用来表示镜像后的坐标
                    landmark = landmark[mirror_idx]
                    # 图像水平翻转
                    imgT = cv2.flip(imgT, 1)
                # 添加到图片数据集
                self.imgs.append(imgT)
                # 添加到关键点坐标集
                self.landmarks.append(landmark)

    def save_data(self, path, prefix):
        # 返回一系列增强后的图像labels
        labels = []
        # TRACKED_POINTS = [0, 2, 3, 5, 6, 7, 8, 9, 10, 12, 11, 19, 20, 15]
        for i, (img, lanmark) in enumerate(zip(self.imgs, self.landmarks)):
            assert lanmark.shape == (21, 2)
            # 生成image保存名
            save_path = os.path.join(path, prefix+'_'+str(i)+'.png')
            # 名字不能重复
            assert not os.path.exists(save_path), save_path
            # 保存增强后的image
            cv2.imwrite(save_path, img)
            # # 获取欧拉角的前提是获得跟踪点的坐标的值
            # euler_angles_landmark = []
            # for index in TRACKED_POINTS:
            #     euler_angles_landmark.append(lanmark[index])
            # euler_angles_landmark = np.asarray(euler_angles_landmark).reshape((-1, 28))
            # # Utils/utils.py近似计算欧拉角的函数
            # pitch, yaw, roll = calculate_pitch_yaw_roll(euler_angles_landmark[0])
            # # 将欧拉角保存为float数组
            # euler_angles = np.asarray((pitch, yaw, roll), dtype=np.float32)
            # # 将欧拉角三个值用空格隔开变成字符串
            # euler_angles_str = ' '.join(list(map(str, euler_angles)))
            # 将landmark还原成字符串
            landmark_str = ' '.join(list(map(str,lanmark.reshape(-1).tolist())))
            # 图片文件位置，坐标点标记，属性标记，欧拉角
            label = '{} {}\n'.format(save_path, landmark_str)
            labels.append(label)
        return labels

# 增强处理后的图片和label的输出目录，原始label.txt，是否为训练的样本
def get_dataset_list(outDir, landmarkDir, is_train):
    with open(landmarkDir, 'r') as f:
        lines = f.readlines()
        labels = []
        # 保存图片的输出目录
        save_img = os.path.join(outDir, 'imgs')
        # 创建保存图片输出的目录
        if not os.path.exists(save_img):
            os.mkdir(save_img)
        # 测试只取前100 lines
        if debug:
            lines = lines[:100]
        for i, line in enumerate(lines):
            # 创建处理对象
            Img = ImageDate(line)
            # imgDir + 图片名
            img_name = Img.path
            # 是否为训练样本， 图片增强次数， 镜像之后坐标点
            Img.load_data(is_train, 50, Mirror_file)
            # os.path.split（）返回文件的路径和文件名
            _, filename = os.path.split(img_name)
            # os.path.splitext(“文件路径”)    分离文件名与扩展名；默认返回(fname, fextension)元组，可做分片操作
            filename, _ = os.path.splitext(filename)
            label_txt = Img.save_data(save_img, str(i)+'_' + filename)
            labels.append(label_txt)
            if ((i + 1) % 100) == 0:
                print('file: {}/{}'.format(i+1, len(lines)))

    with open(os.path.join(outDir, 'labels.txt'), 'w') as f:
        for label in labels:
            f.writelines(label)
# 筛选无效图片的label
def removeInvalidImg(srcImgList):
    resList= []
    for item in srcImgList:
        picDir = item.split()[0]
        if os.path.isfile(picDir):
            resList.append(item)
    return resList
# 按比例ratio生成train.txt test.txt
def loadMetaDataList(SrcImage, ratio):
    folderList = ['I', 'II']
    tmpList = []
    for folderName in folderList:
        picFileDir = os.path.join(SrcImage ,folderName)
        labelFileDir = os.path.join(picFileDir, 'label.txt')
        with open(labelFileDir) as f:
            lines = f.readlines()
        tmpList.extend(list(map((picFileDir + '/').__add__, lines)))
    resLines = removeInvalidImg(tmpList)
    rd.shuffle(resLines)
    total = len(resLines)
    trainNums = int(total * ratio) if int(total * ratio) < total else total
    trainLabelTxt = os.path.join(SrcImage,'train_resnet.txt')
    testLabelTxt = os.path.join(SrcImage,'test_resnet.txt')
    with open(trainLabelTxt, 'w') as wf:
        for wl in resLines[:trainNums]:
            wf.write(wl)
    with open(testLabelTxt, 'w') as wf:
        for wl in resLines[trainNums:]:
            wf.write(wl)

if __name__ == '__main__':
    # 获取当前脚本的文件目录
    root_dir = os.path.dirname(os.path.realpath(__file__))
    SrcImage = os.path.join(root_dir, 'SrcImage')
    loadMetaDataList(SrcImage, 0.7)
    Mirror_file = root_dir + '/' + 'Mirror21.txt'
    landmarkDirs = ['test_resnet.txt', 'train_resnet.txt']
    landmarkDirs = list(map((root_dir + '/' + 'SrcImage' + '/').__add__, landmarkDirs))

    outDirs = ['TestData', 'TrainData']
    for landmarkDir, outDir in zip(landmarkDirs, outDirs):

        outDir = os.path.join(root_dir, outDir)
        print(outDir)
        if os.path.exists(outDir):
            # 表示递归删除文件夹下的所有子文件夹和子文件
            shutil.rmtree(outDir)
            # 创建目录
        os.mkdir(outDir)
        # 判断是否为训练标记txt
        if 'test' in landmarkDir:
            is_train = False
        else:
            is_train = True
        imgs = get_dataset_list(outDir, landmarkDir, is_train)
    print('end')