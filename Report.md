# CPS 595 - Software Engineering Project

# Project Title:  TinyML
### Work updates:
 - Research on Tiny Machine Learning. 
 - Research on the machine learning models.
 - Implementation of tensorflow object detection using a pre-trained model. 
 -

### Tiny Machine learning:
 - Research in the fields of machine learning and embedded systems known as "TinyML" focuses on the kinds of models that may be used on compact, low-power hardware, such as microcontrollers. It provides edge devices with low-latency, low-power, and low-bandwidth model inference. The goal of this research is to develop a machine learning model that can be used in low-power, low-memory embedded devices, although it is extremely unlikely that this model can be implemented in such a device due to its high memory and compute requirements. We utilize the best model that can be used to operate it on a small edge device or an embedded device from the result of our study into the best machine learning model for embedded devices. The Scope of the project is to create a machine learning model that can be deployed and utilized to gather data from embedded devices like an Arduino or Bluefruit device. Also try this concept on various devices that gather data and deliver it to a single cloud server.
 

### Object Detection using Tensorflow:
 - A computer vision technology called object detection helps locate and identify things in an image or video. Using this form of localization and identification, object detection may be used to count the items in a scene, as well as to locate and track them in real time while precisely identifying them.
 - Tensorflow is an open-source toolkit for large-scale machine learning and numerical computing that makes it easier for Google Brain TensorFlow to gather data, train models, deliver predictions, and improve future outcomes.
 - The TensorFlow Object Detection API is an open-source framework built on top of TensorFlow that makes it easy to construct, train and deploy object detection models. There are pre-trained models that have been trained on various datasets such as COCO dataset and The Open Image dataset.

### Implemenation of TensorFlow Object Detection machine learning model: 
 - Installing dependencies :
      In your Terminal Install:
      1. pip install tensorflow
      2. pip install tensorflow-gpu
      3. pip install pillow Cython lxml jupyter matplotlib 
      4. pip install protobuf
 -  Protocol Buffers (protobuf) is like JSON file, except it's faster and smaller and it generates native language bindings.
 - Install the TensorFlow object detection:
    git clone https://github.com/tensorflow/models.git   or  go the link and download the model zip file and unzip the file.
 - Python Package Installation:
   cd models/research
   protoc object_detection/protos/*.proto --python_out=.   # Compile Protos
  cp object_detection/packages/tf2/setup.py .    #Install TensorFlow Object Detection API.
   python -m pip install .
 - Test the installation run:
    python object_detection/builders/model_builder_tf2_test.py
 - When the test compiles without any Error Move to the next step:
 - Download the Object_detection.py file and run it on jupyter notebook.
 - This also Includes real time video stream object detection using OpenCV in the above file.


### Next Process:
 - Research on How the model can detect untrained or unlabelled image.
 - Pruning the model and using TensorFlow-Lite model to implement on Raspberry Pi or an Emulator.
 - Research on peer-to-peer Network and Implementation it on the raspberry pi model or an Emulator.
 - Research on distributed Computing and distributed learning.
 - 

Object Detection Images:

![Object-detection-pic](Images/Object-detection1.png)

![Object-detection](Images/Object-detection2.png)



