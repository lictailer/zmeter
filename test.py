def load_plot(self,data,target_index):
    target_index=target_index[self.setter_level_number+1::]
    reversed_current_target_index=[]
    for i in target_index.reversed():
        reversed_current_target_index.append(i)
    index_list = list(reversed_current_target_index[0:len(target_index) - self.setter_level_number])
    temp = data[self.setter_level_number][self.getter_number]
    print(temp)
    for i in index_list:
        print(i)
        self.y_coordinates = temp[i]
        print(self.y_coordinates)
    self.line = self.plot.plot(list(self.x_coordinates), self.y_coordinates, pen=pg.mkPen(color=(240, 255, 255), width=2))
    print("a")

load_plot(range(10), )