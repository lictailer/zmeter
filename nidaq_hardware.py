import numpy as np
import PyDAQmx as Daq
from PyDAQmx import Task
import ctypes
import time


class NIDAQHardWare:

    def __init__(self):
        self._clock_task = None
        self._counter_tasks = []
        # when not using a second clock channel as reference
        self._sample_counter_task = None
        self._clock_frequency = 100
        self._AOVoltage_minVal = -10
        self._AOVoltage_maxVal = 10
        self._AIVoltage_minVal = -10
        self._AIVoltage_maxVal = 10
        self._AO_dict = {}
        self._AI_dict = {}

    # =================== sample Counter Commands ========================

    def setup_sample_counter(self, chan="/Dev2/ctr0"):
        if self._sample_counter_task is None:
            self._sample_counter_task = Daq.TaskHandle()
            Daq.DAQmxCreateTask("Counter", Daq.byref(self._sample_counter_task))
            Daq.DAQmxCreateCICountEdgesChan(
                self._sample_counter_task,
                chan,
                "Sample Counter Channel",
                Daq.DAQmx_Val_Rising,
                0,
                Daq.DAQmx_Val_CountUp,
            )

            pointer = ctypes.POINTER(ctypes.c_ulong)
            # Create a c_ulong instance
            self.sample_count = ctypes.c_ulong(0)
            # Create a pointer to that c_ulong instance
            self.p_sample_count = pointer(self.sample_count)
        else:
            print("sample counter already setup")

    def get_sample_count(self, wait_time: float):
        if not self._sample_counter_task is None:
            task = self._sample_counter_task
            Daq.DAQmxStartTask(task)
            time.sleep(wait_time)
            Daq.DAQmxReadCounterScalarU32(task, 10.0, self.sample_count, None)
            Daq.DAQmxStopTask(task)
            rate = self.p_sample_count.contents.value / wait_time
            return rate
        else:
            print("sample counter is not setup yet, can't get count")
            return -1

    def close_sample_counter(self):
        if not self._sample_counter_task is None:
            Daq.DAQmxClearTask(self._sample_counter_task)
            self._sample_counter_task = None
        else:
            print("sample counter already closed")

    # =================== Counter Commands ========================

    def setup_clock(self, freq, clock_channel):
        if self._clock_task is None:
            clock_task = Daq.TaskHandle()

            idle = Daq.DAQmx_Val_Low
            task_name = "Clock" + clock_channel.replace("/", "_")
            Daq.DAQmxCreateTask(task_name, Daq.byref(clock_task))

            Daq.DAQmxCreateCOPulseChanFreq(
                clock_task,
                clock_channel,
                "Clock Producer " + clock_channel.replace("/", "_"),
                Daq.DAQmx_Val_Hz,
                idle,
                0,
                freq,
                0.5,
            )

            Daq.DAQmxCfgImplicitTiming(clock_task, Daq.DAQmx_Val_ContSamps, 1000)

            Daq.DAQmxStartTask(clock_task)

            self._clock_frequency = float(freq)
            self._clock_task = clock_task
        else:
            print("clock already started")

    def setup_counter(self, counter_channels, sources, clock_channel):
        if len(self._counter_tasks) == 0:
            for i, ch in enumerate(counter_channels):
                task = Daq.TaskHandle()  # Initialize a Task

                Daq.DAQmxCreateTask("Counter{0}".format(i), Daq.byref(task))

                Daq.DAQmxCreateCISemiPeriodChan(
                    task,
                    ch,
                    "Counter Channel {0}".format(i),
                    0,
                    2e7 / 2 / self._clock_frequency,
                    Daq.DAQmx_Val_Ticks,
                    "",
                )

                Daq.DAQmxSetCISemiPeriodTerm(task, ch, clock_channel + "InternalOutput")

                Daq.DAQmxSetCICtrTimebaseSrc(task, ch, sources[i])

                Daq.DAQmxCfgImplicitTiming(task, Daq.DAQmx_Val_ContSamps, 1000)

                Daq.DAQmxSetReadRelativeTo(task, Daq.DAQmx_Val_CurrReadPos)

                Daq.DAQmxSetReadOffset(task, 0)

                Daq.DAQmxSetReadOverWrite(task, Daq.DAQmx_Val_DoNotOverwriteUnreadSamps)
                self._counter_tasks.append(task)

            for i, task in enumerate(self._counter_tasks):
                Daq.DAQmxStartTask(task)
        else:
            print("counter already started")

    def get_counts(self, samples=None):
        if samples is None:
            samples = 1
        samples = int(samples)
        count_data = np.empty((len(self._counter_tasks), 2 * samples), dtype=np.uint32)

        for i, task in enumerate(self._counter_tasks):
            Daq.DAQmxReadCounterU32(
                task,
                2 * samples,
                50,
                count_data[i],
                2 * samples,
                Daq.byref(Daq.int32()),
                None,
            )

        real_data = np.empty((len(self._counter_tasks), samples), dtype=np.uint32)
        real_data = count_data[:, ::2]
        real_data += count_data[:, 1::2]

        all_data = np.zeros((len(self._counter_tasks), samples), dtype=np.float64)
        all_data = real_data * self._clock_frequency
        return all_data

    def close_counter(self):
        if not len(self._counter_tasks) == 0:
            for task in self._counter_tasks:
                Daq.DAQmxStopTask(task)
                Daq.DAQmxClearTask(task)
            self._counter_tasks = []
        else:
            print("counter already closed")

    def close_clock(self):
        if self._clock_task is not None:
            Daq.DAQmxStopTask(self._clock_task)
            Daq.DAQmxClearTask(self._clock_task)
            self._clock_task = None
        else:
            print("clock already closed")

    # ================ AO voltage Commands =======================

    def setup_single_AO_task(self, physical_channel):
        if self._AO_dict.get(physical_channel) is None:
            task = Task()
            task.CreateAOVoltageChan(
                physical_channel,
                "aa_voltage" + "".join(physical_channel).replace("/", "_"),
                self._AOVoltage_minVal,
                self._AOVoltage_maxVal,
                Daq.DAQmx_Val_Volts,
                None,
            )
            self._AO_dict[physical_channel] = task
            task.StartTask()
        else:
            print(f"AO{physical_channel} already started")

    def write_single_AO_task(self, physical_channel, AO_value):
        self._AO_dict[physical_channel].WriteAnalogScalarF64(True, 10.0, AO_value, None)

    def close_single_AO_task(self, physical_channel):
        if self._AO_dict[physical_channel] is not None:
            self._AO_dict[physical_channel].StopTask()
            self._AO_dict[physical_channel] = None

    # ================ AI voltage Commands =======================
    def set_up_single_AI_task_old(self, physical_channel):
        if self._AI_dict.get(physical_channel) is None:
            task = Daq.TaskHandle()
            task_name = "AI" + physical_channel.replace("/", "_")
            Daq.DAQmxCreateTask(task_name, Daq.byref(task))
            Daq.DAQmxCreateAIVoltageChan(
                task,
                physical_channel,
                "",
                Daq.DAQmx_Val_RSE,
                self._AIVoltage_minVal,
                self._AIVoltage_maxVal,
                Daq.DAQmx_Val_Volts,
                None,
            )
            self._AI_dict[physical_channel] = task
            # Daq.DAQmxStartTask(task)
        else:
            print("AI already started")

    def setup_single_AI_task(self, physical_channel):
        if self._AI_dict.get(physical_channel) is None:
            task = Task()
            task.CreateAIVoltageChan(
                physical_channel,
                "AI_voltage" + "".join(physical_channel).replace("/", "_"),
                Daq.DAQmx_Val_RSE,
                self._AIVoltage_minVal,
                self._AIVoltage_maxVal,
                Daq.DAQmx_Val_Volts,
                None,
            )

            self._AI_dict[physical_channel] = task
        else:
            print(f"AO{physical_channel} already started")

    def read_single_AI_task_old(self, physical_channel):
        data = np.zeros((1,), dtype=np.float64)
        sampsPerChanRead = Daq.int32()
        task = self._AI_dict[physical_channel]
        Daq.DAQmxStartTask(task)  # *****
        Daq.DAQmxReadAnalogF64(
            task,
            1,
            10.0,
            Daq.DAQmx_Val_GroupByChannel,
            data,
            1,
            Daq.byref(sampsPerChanRead),
            None,
        )
        Daq.DAQmxStopTask(task)
        return data[0]

    def read_single_AI_task(self, physical_channel):
        data = np.zeros((1,), dtype=np.float64)
        sampsPerChanRead = Daq.int32()
        task = self._AI_dict[physical_channel]
        task.StartTask()
        task.ReadAnalogF64(
            1,
            10.0,
            Daq.DAQmx_Val_GroupByChannel,
            data,
            1,
            Daq.byref(sampsPerChanRead),
            None,
        )
        task.StopTask()
        return data[0]
    
    def read_mult_AI_task(self, physical_channel, accumalte_num=128):
        """
        Accumulate AI input value, the reading frequency for NI 6002 is ~35000Hz including processing time
        """
        data = np.zeros((accumalte_num), dtype=np.float64)
        sampsPerChanRead = Daq.int32()
        task = self._AI_dict[physical_channel]
        task.StartTask()
        task.ReadAnalogF64(
            accumalte_num,
            10.0,
            Daq.DAQmx_Val_GroupByChannel,
            data,
            accumalte_num,
            Daq.byref(sampsPerChanRead),
            None,
        )
        task.StopTask()
        return data[0:accumalte_num].mean()

    def close_single_AI_task(self, physical_channel):
        if self._AI_dict[physical_channel] is not None:
            self._AI_dict[physical_channel].StopTask()
            self._AI_dict[physical_channel] = None

if __name__ == "__main__":
    n = NIDAQHardWare()
    # n.setup_sample_counter(chan='/dev1/ctr0')
    n.setup_single_AI_task('/dev1/AI1')
    start_time = time.time()

    for i in range(5):
        a=n.read_mult_AI_task('/dev1/AI1', 2047)
        print(a)
    n.close_single_AI_task('/dev1/AI1')

    end_time = time.time()
    print("Time", end_time - start_time)
