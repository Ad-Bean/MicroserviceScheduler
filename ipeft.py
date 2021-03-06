from read_dag import read_dag
import operator
from math import isclose
import numpy as np
from Processor import Processor
from Task import Task

class Task:
    def __init__(self, id):
        self.id = id
        self.processor_id = None
        self.rank = None
        self.comp_cost = []
        self.avg_comp = None
        self.duration = {'start': None, 'end': None}
        self.CNP = False


class Processor:
    def __init__(self, id):
        self.id = id
        self.task_list = []


class IPEFT:
    def __init__(self, input_list=None, file=None, verbose=False, p=3, b=0.5, ccr=0.5):
        if input_list is None and file is not None:
            self.num_tasks, self.num_processors, comp_cost, self.graph = read_dag(
                file, p, b, ccr)
        elif len(input_list) == 4 and file is None:
            self.num_tasks, self.num_processors, comp_cost, self.graph = input_list
        else:
            print('Enter filename or input params')
            raise Exception()

        if verbose:
            print("No. of Tasks: ", self.num_tasks)
            print("No. of processors: ", self.num_processors)
            print("Computational Cost Matrix:")
            for i in range(self.num_tasks):
                print(comp_cost[i])
            print("Graph Matrix:")
            for line in self.graph:
                print(line)

        self.tasks = [Task(i) for i in range(self.num_tasks)]
        self.processors = [Processor(i) for i in range(self.num_processors)]

        for i in range(self.num_tasks):
            self.tasks[i].comp_cost = comp_cost[i]
            self.tasks[i].avg_comp = sum(comp_cost[i]) / self.num_processors

        self.__computeRanks()
        self.tasks.sort(key=lambda x: x.rank, reverse=True)

        if verbose:
            print('AEST: ', self.AEST)
            print('ALST: ', self.ALST)
            print('CN: ', self.CN)
            print('PCT:\n', self.PCT)
            for task in self.tasks:
                print("Task {} -> Rank: {}".format(task.id+1, task.rank))
            print('CNCT:\n', self.CNCT)

        self.__allotProcessor()
        self.makespan = max([t.duration['end'] for t in self.tasks])

    def populate_AEST(self, t):
        if t == self.tasks[0]:
            self.AEST[0] = 0
            return
        aest_preds = []
        for pre in self.tasks:
            if self.graph[pre.id][t.id] != -1:
                if self.AEST[pre.id] == -1:
                    self.populate_AEST(pre)
                aest_preds.append(
                    self.AEST[pre.id] + pre.avg_comp + self.graph[pre.id][t.id])
        self.AEST[t.id] = max(aest_preds)

    def populate_ALST(self, t):
        if t == self.tasks[self.num_tasks-1]:
            self.ALST[t.id] = self.AEST[t.id]
            return
        alst = float('inf')
        for succ in self.tasks:
            if self.graph[t.id][succ.id] != -1:
                if self.ALST[succ.id] == -1:   # ALST not calculated yet
                    self.populate_ALST(succ)
                c_im = self.graph[t.id][succ.id]
                alst = min(alst, self.ALST[succ.id]-c_im)
        self.ALST[t.id] = alst-t.avg_comp

    def populate_PCT(self, t, p):
        if t == self.tasks[self.num_tasks-1]:
            self.PCT[t.id][p.id] = 0
            return
        pct = -float('inf')
        for succ in self.tasks:
            if self.graph[t.id][succ.id] != -1:
                for pm in self.processors:
                    if self.PCT[succ.id][pm.id] == -1:
                        self.populate_PCT(succ, pm)
                    c_ij = self.graph[t.id][succ.id] if p.id != pm.id else 0
                    new_pct = self.PCT[succ.id][pm.id] + \
                        succ.comp_cost[pm.id] + c_ij
                    if pct <= new_pct:
                        best_pm_id = pm.id
                        pct = new_pct
        # if p.id == best_pm_id:
        #     self.PCT[t.id][p.id] = 0
        # else:
        self.PCT[t.id][p.id] = pct

    def populate_CNCT(self, t, p):
        if t == self.tasks[self.num_tasks-1]:
            self.CNCT[t.id][p.id] = 0
            return

        succ_list = np.array(self.graph[t.id])
        succ_cn = np.nonzero(np.logical_and(self.CN, succ_list != -1))[0]
        if succ_cn.size == 0:
            succ_cn = np.nonzero(succ_list != -1)[0]

        curr_max = -float('inf')
        for succ_id in succ_cn:
            succ = self.tasks[succ_id]
            curr_min = float('inf')
            for pm in self.processors:
                if self.CNCT[succ_id][pm.id] == -1:
                    self.populate_CNCT(succ, pm)
                c_ij = self.graph[t.id][succ_id] if p.id != pm.id else 0
                curr_min = min(
                    curr_min, self.CNCT[succ_id][pm.id] + succ.comp_cost[pm.id] + c_ij)
            curr_max = max(curr_max, curr_min)

        self.CNCT[t.id][p.id] = curr_max

    def __computeRanks(self):
        # Assume that task[0] is the initial task, as generated by TGFF
        # Assume that task[num_tasks - 1] is exit task, as generated by TGFF
        # Assume communicate rate is equal between processors

        self.AEST = np.full(self.num_tasks, -1, dtype=float)
        self.populate_AEST(self.tasks[self.num_tasks-1])
        self.ALST = np.full(self.num_tasks, -1, dtype=float)
        self.populate_ALST(self.tasks[0])

        self.CN = np.isclose(self.AEST, self.ALST)
        not_cn = np.nonzero(self.CN == False)
        for i in not_cn[0]:
            t = self.tasks[i]
            for succ in range(self.num_tasks):
                if self.graph[i][succ] != -1:
                    if self.CN[succ] == True:
                        t.CNP = True

        self.PCT = np.full((self.num_tasks, self.num_processors), -1)
        for p in self.processors:
            self.populate_PCT(self.tasks[0], p)

        self.CNCT = np.full((self.num_tasks, self.num_processors), -1)
        for t in self.tasks:
            for p in self.processors:
                if self.CNCT[t.id][p.id] == -1:
                    self.populate_CNCT(t, p)

        avg_pct = np.sum(self.PCT, axis=1) / self.num_processors
        for t in self.tasks:
            t.rank = avg_pct[t.id]+t.avg_comp

    def __get_est(self, t, p):
        est = 0
        for pre in self.tasks:
            # if pre also done on p, no communication cost
            if self.graph[pre.id][t.id] != -1:
                c = self.graph[pre.id][t.id] if pre.processor_id != p.id else 0
                try:
                    est = max(est, pre.duration['end'] + c)
                except:
                    print(pre.id)
                    print(t.id)
                    raise Exception()
        free_times = []
        if len(p.task_list) == 0:       # no task has yet been assigned to processor
            free_times.append([0, float('inf')])
        else:
            for i in range(len(p.task_list)):
                if i == 0:
                    # if p is not busy from time 0
                    if p.task_list[i].duration['start'] != 0:
                        free_times.append(
                            [0, p.task_list[i].duration['start']])
                else:
                    free_times.append(
                        [p.task_list[i-1].duration['end'], p.task_list[i].duration['start']])
            free_times.append([p.task_list[-1].duration['end'], float('inf')])
        for slot in free_times:     # free_times is already sorted based on avaialbe start times
            if est < slot[0] and slot[0] + t.comp_cost[p.id] <= slot[1]:
                return slot[0]
            if est >= slot[0] and est + t.comp_cost[p.id] <= slot[1]:
                return est

    def __allotProcessor(self):

        for t in self.tasks:
            curr_eft_cnct = float("inf")
            for p in self.processors:
                est = self.__get_est(t, p)
                eft = est + t.comp_cost[p.id]
                if not t.CNP:
                    eft_cnct = eft + self.CNCT[t.id][p.id]
                else:
                    eft_cnct = eft
                if eft_cnct < curr_eft_cnct:   # found better case of processor
                    curr_eft_cnct = eft_cnct
                    aft = eft
                    best_p = p.id

            t.processor_id = best_p
            t.duration['start'] = aft - t.comp_cost[best_p]
            t.duration['end'] = aft
            self.processors[best_p].task_list.append(t)
            self.processors[best_p].task_list.sort(
                key=lambda x: x.duration['start'])

    def __str__(self):
        print_str = ""
        for p in self.processors:
            print_str += 'Processor {}:\n '.format(p.id+1)
            for t in p.task_list:
                print_str += 'Task {}: start = {}, end = {}\n'.format(
                    t.id+1, t.duration['start'], t.duration['end'])
        print_str += "Makespan = {}\n".format(self.makespan)
        return print_str


if __name__ == "__main__":
    from argparse import ArgumentParser
    ap = ArgumentParser()
    ap.add_argument('-i', '--input', required=True,
                    help="DAG description as a .dot file")
    args = ap.parse_args()
    new_sch = IPEFT(file=args.input, verbose=True, p=4, b=0.1, ccr=0.1)
    print(new_sch)
