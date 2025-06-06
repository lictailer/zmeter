import numpy as np


class Brakets:
    def __init__(self,
                 cmd='[BA]',
                 destinations={'A': [100, 101],
                               'B': [110],
                               'C': [120, 121],
                               'D': [130, 131],
                               'E': [140],
                               'F': [150], }):
        self.cmd = cmd
        self.destinations = destinations
        self.all_channels = list(destinations.keys())
        self.output = np.empty([len(self.all_channels), self.find_cmd_length(cmd)])
        self.output[:, :] = np.nan

        self.unpack(cmd)
        # print(self.output)

    def un_braket(self, cmd):
        """
        un-braket a single level.
        (A[(BC)(DE)]F)  --> A, [(BC)(DE)], F
        """
        if cmd[0] not in ['(', '[']:
            return []
        if cmd[0] == '(':
            kuohao = '()'
        else:
            kuohao = '[]'

        cmd = cmd[1:-1]
        elements = []
        while cmd != '':
            temp = ''
            if cmd[0] == '(':
                counter = 1
                temp += cmd[0]
                cmd = cmd[1:]
                while counter != 0:
                    if cmd[0] == '(':
                        counter += 1
                        temp += cmd[0]
                        cmd = cmd[1:]
                    elif cmd[0] == ')':
                        counter -= 1
                        temp += cmd[0]
                        cmd = cmd[1:]
                    else:
                        temp += cmd[0]
                        cmd = cmd[1:]
                elements.append(temp)
                temp = ''
            elif cmd[0] == '[':
                counter = 1
                temp += cmd[0]
                cmd = cmd[1:]
                while counter != 0:
                    if cmd[0] == '[':
                        counter += 1
                        temp += cmd[0]
                        cmd = cmd[1:]
                    elif cmd[0] == ']':
                        counter -= 1
                        temp += cmd[0]
                        cmd = cmd[1:]
                    else:
                        temp += cmd[0]
                        cmd = cmd[1:]
                elements.append(temp)
                temp = ''
            else:
                elements.append(cmd[0])
                cmd = cmd[1:]
        return elements

    def find_cmd_length(self, cmd):
        """
        get what is the round of the setting id when cmd runs up.
        calculate recursivly.
        """
        n = 0
        if cmd == '':
            return 0

        elif cmd[0] == '(':
            for c in self.un_braket(cmd):
                n += self.find_cmd_length(c)

        elif cmd[0] == '[':
            temp_id=[]
            for sub_bracket in self.un_braket(cmd):
                temp_id.append(self.find_cmd_length(sub_bracket))
            n += max(temp_id)

        else:
            # letter = cmd[0]
            # n += len(self.destinations[letter])
            # at this point the command should already be single letters
            n += len(self.destinations[cmd])

        return n

    def unpack(self, cmd, id=0):
        """
        inserting the correct destination of the corresponding master to the correct position in the array.
        id is where to start adding the numbers to the array.
        if finished an '(' insert, id should adding up the just finished cmd length.
        if finished an '[' insert, id should not adding up the just finished cmd length.
        if finally meets an letter, filling up the array
        """
        if cmd == '':
            return

        elif cmd[0] == '(':
            for sub_bracket in self.un_braket(cmd):
                self.unpack(sub_bracket, id=id)
                id += self.find_cmd_length(sub_bracket)

        elif cmd[0] == '[':
            for sub_bracket in self.un_braket(cmd):
                self.unpack(sub_bracket, id=id)

        else:  # at this point the command should already be single letters
            for i in range(len(self.destinations[cmd])):
                channel_id = self.all_channels.index(cmd)
                self.output[channel_id, id] = self.destinations[cmd][i]
                id += 1  # this is only for filling one by one


if __name__ == "__main__":
    # Brakets()
    Brakets(cmd='[AB]',
            destinations={'A': [100, 101, 102],
                          'B': [110,100, 101, 102],
                           })
