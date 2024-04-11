""" Vision-based closed-loop printing workflow execusion

This is the main file to run the FDM 3D printing workflow with integrated 
real-time defect detection and correction capabilities. The workflow is 
initiated by specifying the 3D model files to be printed and configuring 
the desired print parameters. Once the print job starts, the system 
automatically engages its monitoring and defect detection mechanisms.
"""

import cv2
from defect_detection import DefectDetection
from gcode_ironing import generate_iron_layer
from camera_control import CameraControl
from layer_parsing_separate import parse_layer
from gcode_nozzle_move_config_filewise import add_nozzle_movement
from gcode_sender import GcodeSender
from printrun.printcore import printcore
from printrun import gcoder
import time
import os
import requests

# Path to related files and directories
gcode_path = 'printer_communication/gcode/SmallBellow_Zwiping_37mm_generic_Oct30_0.3mm.gcode'
gcode_noTri_path = 'printer_communication/gcode/SmallBellow_only_Oct29_0.3mm.gcode'
img_dir_path = 'printer_communication/images/elp_0301_0/'
log_dir_path = 'printer_communication/logs/'
log_file_name = '0301_shooting.txt'
bellow_dir = "printer_communication/bellow_layer_gcode_file/"
tri_dir = "printer_communication/triangle_layer_gcode_file/"
cor_gcode_dir = 'printer_communication/iron_layer_gcode_file/'

# Hyperparameters
parse_support_line = 1
layer_height = 0.3
delay_time = 3
enable_correction = True
fixing_E_proportion = 0.2
fixing_S_proportion = 0.6
total_layer = 80
move_X = 180    # X coordinates for camera position
move_Y = 152    # Y coordinates for camera position 
img_taken_position = [move_X, move_Y]
# threashold information for defect detection
defect_threshold = 2
binary_threshold = 85
first_layer_binary_threshold = 90
top_layer_binary_threshold = 80


# Log file setup
with open(log_dir_path + log_file_name, 'a') as f:
    f.write("Gcode path: {}\n".format(gcode_path))
    f.write("Image folder path: {}\n".format(img_dir_path))
    f.write("Picture taking position: {}\n".format(img_taken_position))
    f.write("Total layer: {}\n".format(total_layer))
    f.write("Defect binary threshold: {}\n".format(binary_threshold))
    f.write("First binary threshold: {}\n".format(first_layer_binary_threshold))
    f.write("Top binary threshold: {}\n".format(top_layer_binary_threshold))
    f.write("Defect number threshold: {}\n".format(defect_threshold))
    f.write("Layer height: {}\n".format(layer_height))
    f.write("Correction enabled: {}\n".format(enable_correction))
    f.write("Ironing layer extrusion ratio: {}\n".format(fixing_E_proportion))
    f.write("Ironing layer speed ratio: {}\n".format(fixing_S_proportion))
    f.write("---------------------------------------------------------\n")

# Parse gcode file layer by layer
parse_layer(gcode_path, bellow_dir, tri_dir)
print("Layers parsed")
# Add nozzle movement for camera position
add_nozzle_movement(bellow_dir, move_X, move_Y)
print("Movement modified")
# Open and set up camera
camera = CameraControl(1)
print("Camera opened")
# Establish connection with printer
gcode_sender = GcodeSender("COM3")
print("Connected to printer")
# Start by sending the setup commands
gcode_sender.send_gcode(bellow_dir + "layer_0.gcode")
print("Start heating")
# Start defect detector
defect_detector = DefectDetection(gcode_noTri_path, img_dir_path, img_taken_position, layer_height)
fixed_layer_list = []

# post notification to phone
requests.post("https://ntfy.sh/RMG_close_loop_printer",
              data=f"Print Starting\nLog: {log_file_name}".encode(encoding='utf-8'))

for i in range(1, total_layer+1):
    # Print the current layer and take picture
    layer_gcode = bellow_dir + "layer_{}.gcode".format(i)
    print("Printing layer {}...".format(i))
    gcode_sender.send_gcode(layer_gcode)
    print("finished printing layer {}".format(i))
    time.sleep(delay_time)
    print("start taking picture")
    img_path = img_dir_path + 'layer_{}.jpg'.format(i)
    camera.take_pic(img_path, i)
    img = cv2.imread(img_path)

    # Determine the defect detection threshold
    if i < 3:
        curr_binary_threshold = first_layer_binary_threshold
    if i > 75:
        curr_binary_threshold = top_layer_binary_threshold
    else:
        curr_binary_threshold = binary_threshold
    coord_list = defect_detector.get_defect_positions(img, i, type=1, binary_threshold=curr_binary_threshold)
    print("layer {} defect: {}".format(i, len(coord_list)))
    line = "layer {}, num of defect: {}".format(i, len(coord_list))
    # print the Z supplement
    z_gcode = tri_dir + "layer_{}.gcode".format(i)
    gcode_sender.send_gcode(z_gcode)

    if len(coord_list) < defect_threshold:
        with open(log_dir_path + log_file_name, 'a') as f:
            f.write(line + '\n')
    else:
        # Start ironing if the number of defect exceeds the threshold
        print("start fixing")
        fixed_layer_list.append(i)
        with open(log_dir_path + log_file_name, 'a') as f:
            f.write(line + ' FIXED\n')
        if enable_correction:
            # Correction procedure
            output_path = cor_gcode_dir + "layer_{}_cor.gcode".format(i)
            generate_iron_layer(layer_gcode, output_path, 
                                E_proportion = fixing_E_proportion, 
                                S_proportion = fixing_S_proportion)
            print("Fixing layer {}...".format(i))
            gcode_sender.send_gcode(output_path)
            print("finished fixing layer {}".format(i))
            time.sleep(delay_time)
            print("start taking correction picture")
            img_path = img_dir_path + 'layer_{}_corrected.jpg'.format(i)
            camera.take_pic(img_path, i)
            # print the Z supplement
            z_output_path = tri_dir + "layer_{}_cor.gcode".format(i)
            generate_iron_layer(layer_gcode, z_output_path, 
                                E_proportion = fixing_E_proportion, 
                                S_proportion = 1)
            gcode_sender.send_gcode(z_gcode)

# send the finishing Gcode
gcode_sender.send_gcode(bellow_dir + "end.gcode")

with open(log_dir_path + log_file_name, 'a') as f:
    f.write("TOTAL NUM OF FIXED LAYER: {}\n".format(len(fixed_layer_list)))
    f.write("Fixed layer list: {}".format(fixed_layer_list))


# post notification to phone
requests.post("https://ntfy.sh/RMG_close_loop_printer",
              data="Print Finished\n\
                    TOTAL NUM OF FIXED LAYER: {}\n\
                    Fixed layer list: {}".format(
                        len(fixed_layer_list), fixed_layer_list
                        ).encode(encoding='utf-8'))
