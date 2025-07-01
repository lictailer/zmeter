from .scan_info import *
from copy import deepcopy

class Construct:
    def __init__(self,info=None) -> None:
        self.info=info
        self.current_destination_index=0
        self.current_values_to_set_index=0

    def construct(self,info):
        temp=self.construct_directories(info)
        # output=[self.flatten_list(temp[0]),self.flatten_list(temp[1])]
        output=[self.diy_flatten(temp[0]),self.flatten_list(temp[1])]
        
        self.values_to_set, self.destinations=output

        # output=self.assign_channel(output)

        # print(temp)
        return output


    def get_points(self,setting_info):
        if isinstance(setting_info[0],list):
            output=[]
            setting_info_length=len(setting_info[0])
            for index in range(setting_info_length):
                temp_point=[]
                for setter_setting_info in setting_info:
                    temp_point.append(setter_setting_info[index])
                output.append(temp_point)
            return(output)
        else:
            return(setting_info)
        

    def construct_directories(self,info):
        current_scan=info['levels']
        points_directory=[]
        channel_directory=[]
        for level,value in current_scan.items():
            points=value['setting_array']
            if isinstance(points,np.ndarray):
                points_directory.append({level:self.get_points(points.tolist())})
            else:
                points_directory.append({level:self.get_points(points)})

            channel_directory.append({level:[]})
            for setter,v in value['setters'].items():
                channel_directory[int(level[-1])][level].append(v['channel'])
        points_directory.reverse()
        channel_directory.reverse()
        # print(points_directory)
        # print(channel_directory)
        return(self.construct_points(points_directory,channel_directory))
        

    def construct_points(self,points_directory,channel_directory):
        points_copy=deepcopy(points_directory)
        points_temp=points_copy.pop(0)
        channel_copy=deepcopy(channel_directory)
        channel_temp=channel_copy.pop(0)
        points_output=[]
        channel_output=[]
        if not points_copy:
            # print(points_temp)
           
            for key,value in points_temp.items():
                channel_output.append(next(iter(channel_temp.keys())))
                # print(value)
                # print(list(channel_temp.values())[0])
                for i in value:
                    points_output.append(i)
                    channel_output.append(list(channel_temp.values())[0])
                return (points_output,channel_output)
        else:
            points_copy=deepcopy(points_copy)
            channel_copy=deepcopy(channel_copy)

            for i in points_temp.values():
                for j in i:
                    channel_output.append(next(iter(channel_temp.keys())))
                    points_output.append(j)
                    channel_output.append(list(channel_temp.values())[0])
                    constructed_points=self.construct_points(points_copy,channel_copy)
                    # print("constructed_points:",constructed_points)
                    # for k in constructed_points[0]:
                    #     print('k:',k)
                    #     print('constructed_points[1]',constructed_points[1])
                    points_output.append(constructed_points[0])
                        
                        # print(k,constructed_points[1])
                    channel_output.append(constructed_points[1])
        return(points_output,channel_output)
    

    def flatten_list(self,nested_list):
   
        flat_list = []  # Initialize the list that will store the flattened elements

        # Function to recursively traverse and flatten the list
        def flatten(sublist):
            for item in sublist:
                if isinstance(item, list):  # If the item is a list, recursively flatten it
                    flatten(item)
                else:  # If the item is not a list, append it to the flat_list
                    flat_list.append(item)

        flatten(nested_list)  # Start the flattening process
        return flat_list
    def diy_flatten(self,x):
        result = []
        for item in x:
            # Check if the item is a list that contains further nested lists (excluding strings)
            if isinstance(item, list) and any(isinstance(subitem, list) for subitem in item):
                # Flatten the list by one level, keeping inner lists intact
                result.extend(self.diy_flatten_one_level(item))
            else:
                # For items that are not lists or are the innermost lists, add them directly to the result
                result.append(item)
        return result

    def diy_flatten_one_level(self,lst):
        """Flatten the list by one level, keeping inner lists intact."""
        flattened = []
        for item in lst:
            if isinstance(item, list) and any(isinstance(subitem, list) for subitem in item):
                # For lists containing further nested lists, extend to add elements of the list
                flattened.extend(item)
            else:
                # For items that are not further nested lists, append them directly
                flattened.append(item)
        return flattened
    def scan_point(self):
        destination=self.destinations[self.current_destination_index]
        value=self.values_to_set[self.current_values_to_set_index]
        output=[]
        if "level" in destination:
            print("Scanning level"+destination[-1])
            self.current_destination_index+=1
            return(self.scan_point())
        if isinstance(value, list):
            for i in range(len(value)):
                temp=[]
                destination = self.destinations[self.current_destination_index]
                temp.append(value[i])
                temp.append(destination)
                # output.append(temp)
                self.current_destination_index += 1
        else:
            destination = self.destinations[self.current_destination_index]
            output.append(value)
            output.append(destination)                
            self.current_destination_index += 1
        return(output)
    
    # def assign_channel(self,input):
    #     output={}
    #     main_list=input[0]
    #     channel_list=input[1]
    #     channel_index=0
    #     for value in main_list:
    #         if isinstance(value,list):
    #             for i in value:
    #                 output[channel_list[channel_index]]=i
    #                 channel_index+=1
    #         else:
    #             output[channel_list[channel_index]]=value
    #             channel_index+=1
    #     return output

            


if __name__ == "__main__":
    info={
        "levels": {
        "level0": {
            "setters": {
            "setter0": {
                "channel": "Lockin1_A",
                "explicit": False,
                "linear_setting": {
                "start": 0,
                "end": 2,
                "step": 1,
                "mid": 1,
                "span": 2,
                "points": 3,
                "destinations": [0.0, 1.0, 2.0]
                },
                "explicit_setting": [-2, 2, 0],
                "destinations": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
            },
            "setter1": {
                "channel": "Lockin2_f",
                "explicit": False,
                "linear_setting": {
                "start": 0,
                "end": 10,
                "step": 1,
                "mid": 5,
                "span": 10,
                "points": 11,
                "destinations": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
                },
                "explicit_setting": [-1, 1, 0],
                "destinations": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
            }
            },
            "setting_method": "[AB]",
            "getters": [],
            "setting_array": [
            [0.0, 1.0, 2.0,],
            [8.0, 9.0, np.NaN]
            ]
        },
        "level1": {
            "setters": {
            "setter0": {
                "channel": "Lockin1_p",
                "explicit": False,
                "linear_setting": {
                "start": 0,
                "end": 2,
                "step": 1,
                "mid": 1,
                "span": 2,
                "points": 3,
                "destinations": [0.0, 1.0, 2.0]
                },
                "explicit_setting": [-2, 2, 0],
                "destinations": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
            }
            },
            "setting_method": "A+B,CD",
            "getters": [],
            "setting_array": 
            [0.0, 1.0, 2.0,]
            
        },
        "level2": {
            "setters": {
            "setter0": {
                "channel": "Lockin2_p",
                "explicit": False,
                "linear_setting": {
                "start": 0,
                "end": 2,
                "step": 1,
                "mid": 1,
                "span": 2,
                "points": 3,
                "destinations": [0.0, 1.0, 2.0]
                },
                "explicit_setting": [-2, 2, 0],
                "destinations": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
            }
            },
            "setting_method": "A+B,CE",
            "getters": [],
            "setting_array": 
            [0.0, 1.0, 2.0,]
            
        }
        },
        "data": {},
        "plots": {
        "line_plots": {},
        "image_plots": {}
        },
        "name": "3"
    }
    if __name__=="__main__":
        construct=Construct()
        constructed_info=construct.construct(info)
        print(construct.values_to_set)
        print(construct.destinations)
        # print(len(construct.values_to_set))

        for i in range(len(construct.values_to_set)):
            print(construct.scan_point())
        # print(len(constructed_info[0]),len(constructed_info[1]))
        # construct.construct_directories(info[0])

