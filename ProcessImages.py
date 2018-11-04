# -*- coding: utf-8 -*-
"""
Created on Sat Nov  3 11:49:34 2018

@author: Craig
"""

import glob

import time

import pandas as pd
import torch

from yolo_v3 import yolo_v3
import cv2
import pickle as pkl

import random
#    import torch.nn as nn
#    import os
#    import os.path as osp
import numpy as np
#    import matplotlib.pyplot as plt
#    from PIL import Image
#    from torchvision import transforms, datasets
#    from torch.utils.data import DataLoader
from utilis import load_classes, parse_cfg, get_test_input
from utilis import create_module, letterbox_image, prep_image, filter_results

# %% Setup paths

path_RawData = "../1RawData/"
path_ProcessedData = "../2ProcessedData/"
path_Predictions = "../5Predictions/"

filename_Predictions = path_Predictions + 'Predictions.csv'

# %%

# layer_type_dic, module_list = create_module(blocks)
# it might imporve performance
# torch.backends.cudnn.benchmark = True

# change cuda to True if you wish to use gpu
cuda = False
colors = pkl.load(open("../4Others/pallete", "rb"))
#    images = "../1RawData/"
#    det = "../2ProcessedData/"
classes = load_classes('../4Others/coco.names')
batch_size = 12
# Used in filter_results to apply a confidence mask
confidence = float(0.5)
# Used in filter_results to remove points with IoU < nms_thesh
nms_thesh = float(0.4)
start = 0
num_classes = 80
cfg_path = "../4Others/yolov3.cfg"
blocks = parse_cfg(cfg_path)

# setup our model object from the yolo_v3.py file
model = yolo_v3(blocks)
model.load_weights("../4Weights/yolov3.weights")
if cuda:
    model = model.cuda()
for params in model.parameters():
    params.requires_grad = False
model.layer_type_dic['net_info']["height"] = 416
model.layer_type_dic['net_info']["width"] = 416
inp_dim = int(model.layer_type_dic['net_info']["height"])

# yolo v3 down size the imput images 32 strides, therefore the input needs to
# be a multiplier of 32 and > 32
assert inp_dim % 32 == 0
assert inp_dim > 32

# put to evaluation mode so that gradient wont be calculated
model.eval()


# %% Load in the images to be processed
load_batch = time.time()

list_images = glob.glob(path_ProcessedData + '*.png')
# Load only the first few images to test the code.
#list_images = glob.glob(path_ProcessedData + '*.png')[0:batch_size*2]

df_Predictions = pd.DataFrame()


for indexes in range(0, len(list_images), batch_size):
    list_images_current = list_images[indexes:indexes+batch_size]
    loaded_images = [cv2.imread(image) for image in list_images_current]

#     %%

    im_batches = list(map(prep_image,
                          loaded_images,
                          [inp_dim] * len(list_images_current)))

    im_dim_list = [(image.shape[1], image.shape[0]) for image in loaded_images]
    im_dim_list = torch.FloatTensor(im_dim_list).repeat(1, 2)
    if cuda:
        im_dim_list = im_dim_list.cuda()

    leftover = 0
    if (len(im_dim_list) % batch_size):
        leftover = 1

    if batch_size != 1:
        num_batches = len(list_images_current) // batch_size + leftover
        im_batches = [torch.cat((im_batches[batch_index*batch_size: min((batch_index + 1)*batch_size,
                      len(im_batches))])) for batch_index in range(num_batches)]


    write = 0
    start_det_loop = time.time()

#    %%

    for i, batch in enumerate(im_batches):
        # load the image
        start = time.time()
        if cuda:
            batch = batch.cuda()

        prediction = model(batch, cuda)

    #    prediction = filter_results(prediction, confidence, nms_thesh)
        prediction = filter_results(prediction, confidence, num_classes, nms_thesh)

        end = time.time()

        if type(prediction) == int:

            for im_num, image in enumerate(
                    list_images_current[i*batch_size: min((i + 1)*batch_size,
                                                  len(list_images_current))]):
                im_id = i*batch_size + im_num
                print("{0:20s} predicted in {1:6.3f} seconds".
                      format(image.split("/")[-1], (end - start)/batch_size))
                print("{0:20s} {1:s}".format("Objects Detected:", ""))
                print("----------------------------------------------------------")
            continue

        prediction[:, 0] += i*batch_size  # transform the attribute from index in batch to index in list_images_current

        if not write:  # If we have't initialised output
            output = prediction
            write = 1
        else:
            output = torch.cat((output, prediction))

        for im_num, image in enumerate(list_images_current[i*batch_size: min((i +  1)*batch_size, len(list_images_current))]):
            im_id = i*batch_size + im_num
            objs = [classes[int(x[-1])] for x in output if int(x[0]) == im_id]
            print("{0:20s} predicted in {1:6.3f} seconds".format(image.split("/")[-1], (end - start)/batch_size))
            print("{0:20s} {1:s}".format("Objects Detected:", " ".join(objs)))
            print("----------------------------------------------------------")

        if cuda:
            torch.cuda.synchronize()

#     %%

    try:
        output
    except NameError:
        print("No detections were made")
        exit()

#     %% Inverse scaling the image size

    im_dim_list = torch.index_select(im_dim_list, 0, output[:, 0].long())

    scaling_factor = torch.min(inp_dim/im_dim_list, 1)[0].view(-1, 1)

    # scaling the image back to its orginal dimensions for drawing.
    output[:, [1, 3]] -= (inp_dim - scaling_factor*im_dim_list[:, 0].view(-1, 1))/2
    output[:, [2, 4]] -= (inp_dim - scaling_factor*im_dim_list[:, 1].view(-1, 1))/2
    output[:, 1:5] /= scaling_factor
    for i in range(output.shape[0]):
        output[i, [1, 3]] = torch.clamp(output[i, [1, 3]], 0.0, im_dim_list[i, 0])
        output[i, [2, 4]] = torch.clamp(output[i, [2, 4]], 0.0, im_dim_list[i, 1])
    output_recast = time.time()
    class_load = time.time()
    draw = time.time()

#     %% Convert the predictions into a dataframe for storage.

    columns = ['x_center', 'y_center', 'width', 'height', 'confidence', 'other1', 'class']

    df_Predictions_current = pd.DataFrame(np.array(output[:, 1:8]), columns=columns)
    df_Predictions_current['filename'] = np.array(output[:, 0])
    df_Predictions_current['filename'] = df_Predictions_current['filename'].apply(lambda x: list_images_current[int(x)])

    columns = ['filename'] + columns
    df_Predictions_current = pd.DataFrame(df_Predictions_current, columns=columns)

    # either create predictions or overwrite it depending on which time
    # through the loop.
    if len(df_Predictions) == 0:
        df_Predictions = df_Predictions_current.copy()
    else:
        df_Predictions = pd.concat([df_Predictions, df_Predictions_current], ignore_index=True)

    df_Predictions.to_csv(filename_Predictions)

# %%

def write(x, results):
    c1 = tuple(x[1:3].int())
    c2 = tuple(x[3:5].int())
    img = results[int(x[0])]
    cls = int(x[-1])
    # FIXME: change this to be non-random
    color = random.choice(colors)
    label = "{0}".format(classes[cls])
    # draw the rectangle around the image
    cv2.rectangle(img, c1, c2, color, 1)

    # draw a rectangle to put the label in
    t_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_PLAIN, 1, 1)[0]
    c2 = c1[0] + t_size[0] + 3, c1[1] + t_size[1] + 4
    cv2.rectangle(img, c1, c2, color, -1)
    cv2.putText(img, label, (c1[0], c1[1] + t_size[1] + 4), cv2.FONT_HERSHEY_PLAIN, 1, [225, 255, 255], 1)
    return img

# %%

outputs = list(map(lambda x: write(x, loaded_images), output))
#cv2.imshow('demo', outputs[0]); key = cv2.waitKey(1)
det_names = pd.Series(list_images_current).apply(lambda x: "{}/det_{}".format(path_ProcessedData, x.split("/")[-1]))
list(map(cv2.imwrite, det_names, loaded_images))
end = time.time()
print("SUMMARY")
print("----------------------------------------------------------")
print("{:25s}: {}".format("Task", "Time Taken (in seconds)"))
print()
#print("{:25s}: {:2.3f}".format("Reading addresses", load_batch - read_dir))
print("{:25s}: {:2.3f}".format("Loading batch", start_det_loop - load_batch))
print("{:25s}: {:2.3f}".format("Detection (" + str(len(list_images_current)) +  " images)", output_recast - start_det_loop))
print("{:25s}: {:2.3f}".format("Output Processing", class_load - output_recast))
print("{:25s}: {:2.3f}".format("Drawing Boxes", end - draw))
print("{:25s}: {:2.3f}".format("Average time_per_img", (end - load_batch)/len(list_images_current)))
print("----------------------------------------------------------")

if cuda:
    torch.cuda.empty_cache()
