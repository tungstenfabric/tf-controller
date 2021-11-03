import os
import grpc
import json
import logging
import datetime
import random
import string
import subprocess
import binascii

from containerd.services.containers.v1 import containers_pb2_grpc, containers_pb2
from containerd.services.tasks.v1 import tasks_pb2_grpc, tasks_pb2
from nodemgr.common.sandesh.nodeinfo.cpuinfo.ttypes import ProcessCpuInfo


class ContainerdContainerMemoryCpuUsage:
    def __init__(self, last_cpu_, last_time_, query_, id_):
        self._query = query_
        self._id = id_
        self._last_cpu = last_cpu_
        self._last_time = last_time_

    @property
    def last_cpu(self):
        return self._last_cpu

    @property
    def last_time(self):
        return self._last_time

    def _convert_time(time):
        # ctr metrics returns timestamp with 9 subseconds
        # cut the last symbols until we get isoformat
        # TODO: if we need timestamp in seconds?
        # TODO: we're loosing timezone
        while time:
            try:
                timestamp = datetime.datetime.fromisoformat(time)
                return int(timestamp.timestamp())
            except ValueError:
                time = time[:-1]

    def get_process_mem_cpu_info(self):
        y = self._query()
        if not y:
            return None

        output = ProcessCpuInfo()
        if 'memory.usage_in_bytes' in y:
            output.mem_res = int(y["memory.usage_in_bytes"]) // 1024
            output.mem_virt = int(y["memory.usage_in_bytes"]) // 1024

        if hasattr(y, 'cpu'):
            u = self._last_cpu
            d = int(y["cpuacct.usage"]) - u \
                if u else 0
            timestamp = self._convert_time(y[self._id])
            D = timestamp - self._last_time

            self._last_cpu = int(y["cpuacct.usage"])
            self._last_time = timestamp

            output.cpu_share = round(d / D, 2) if 0 < D else 0

        return output


class Instrument:
    @staticmethod
    def craft_date_string(nanos_):
        t = divmod(nanos_.ToNanoseconds(), 1e9)
        d = datetime.datetime.fromtimestamp(t[0])
        return d.strftime('%Y-%m-%dT%H:%M:%S.{:09.0f}%z').format(t[1])

    @staticmethod
    def craft_status_string(enum_):
        if 1 == enum_:
            return 'created'
        if 2 == enum_:
            return 'running'
        if 3 == enum_:
            return 'stopped'
        if 4 == enum_:
            return 'paused'
        if 5 == enum_:
            return 'pausing'

        # CONTAINER_UNKNOWN and the rest
        return 'unknown'

    @staticmethod
    def craft_node_type_surrogate(labels_):
        v = os.getenv('VENDOR_DOMAIN', 'net.juniper.contrail')
        if not v:
            return None

        n = labels_.get('io.kubernetes.container.name', '')
        s = labels_.get(v + '.service')
        c = n.split('_', 2)
        return c[1] if 3 == len(c) and (c[0], c[2]) == ('contrail', s) \
            else None


class ViewAdapter:
    @staticmethod
    def craft_list_item(protobuf_, tasks_dict):
        if not protobuf_:
            return None

        output = dict()
        output['Id'] = protobuf_.id
        output['Name'] = protobuf_.metadata.name \
            if hasattr(protobuf_, 'metadata') else protobuf_.id
        if protobuf_.id in tasks_dict:
            t = tasks_dict[protobuf_.id]
            output['State'] = Instrument.craft_status_string(t.status)
        else:
            output['State'] = 'exited'
        output['Labels'] = protobuf_.labels \
            if hasattr(protobuf_, 'labels') else dict()
        output['Created'] = Instrument.craft_date_string(protobuf_.created_at)

        return output

    @staticmethod
    def craft_info(protobuf_, tasks_dict):
        if not (protobuf_ and hasattr(protobuf_, 'spec')):
            return None

        c = dict()
        spec = protobuf_.spec.value
        spec = json.loads(protobuf_.spec.value)
        if 'process' in spec:
            c['Env'] = spec['process'].get('env', [])

        output = {'Config': c}
        S = dict()
        c['Id'] = output['Id'] = protobuf_.id
        if 'Env' not in c:
            x = Instrument.craft_node_type_surrogate(protobuf_.labels)
            if x:
                c['Env'] = ['NODE_TYPE=%s' % x]

        output['Name'] = protobuf_.metadata.name if hasattr(protobuf_, 'metadata') else protobuf_.id
        if not output['Name']:
            output['Name'] = protobuf_.id

        output['State'] = S
        output['Labels'] = protobuf_.labels
        output['Created'] = Instrument.craft_date_string(protobuf_.created_at)

        if protobuf_.id in tasks_dict:
            t = tasks_dict[protobuf_.id]
            S['Pid'] = t.pid
            S['Status'] = Instrument.craft_status_string(t.status)
        else:
            S['Pid'] = 0
            S['Status'] = 'exited'
        # TODO: updated at?
        S['StatedAt'] = Instrument.craft_date_string(protobuf_.started_at) \
            if hasattr(protobuf_, 'started_at') and protobuf_.started_at > 0 else ''

        return output


class ContainerdContainersInterface:
    @staticmethod
    def craft_containerd_peer():
        return ContainerdContainersInterface()._set_channel('/run/containerd/containerd.sock')

    def _set_channel(self, value_):
        if not os.path.exists(value_):
            raise LookupError(value_)

        c = grpc.insecure_channel('unix://{0}'.format(value_))
        self._client = containers_pb2_grpc.ContainersStub(c)
        self._tasks = tasks_pb2_grpc.TasksStub(c)
        self._namespace = os.getenv('CONTAINERD_NAMESPACE', 'k8s.io')
        return self

    def _get_tasks_dict(self):
        tasks_dict = dict()
        q = tasks_pb2.ListTasksRequest()
        metadata = (('containerd-namespace', self._namespace),)
        tasks = self._tasks.List(q, metadata=metadata).tasks
        for task in tasks:
            tasks_dict[task.id] = task

        return tasks_dict

    def _parse_metrics(self, arguments_):
        a = arguments_
        c, o = self._execute(a)
        if 0 != c:
            # NB. there is nothing to parse
            return (c, None)
        try:
            out = o.decode('UTF8')
            metric_dict = dict()
            for line in out.split('\n'):
                ls = line.split(' ', 1)
                if len(ls) == 2:
                    metric_dict[ls[0]] = ls[1].lstrip().rstrip()
            return (c, metric_dict)
        except Exception:
            logging.exception('metrics parsing')
            return (c, None)

    def _execute(self, arguments_, timeout_=10):
        a = ["ctr", "-n", self._namespace]
        a.extend(arguments_)
        p = subprocess.Popen(a, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            o, e = p.communicate(timeout_)
        except subprocess.TimeoutExpired:
            p.kill()
            o, e = p.communicate()
        p.wait()
        if e:
            logging.critical(e)

        return (p.returncode, o)

    def list(self, all_=True):
        tasks_dict = self._get_tasks_dict()
        q = containers_pb2.ListContainersRequest()
        try:
            metadata = (('containerd-namespace', self._namespace),)
            containers = self._client.List(q, metadata=metadata).containers
            # TODO: check if filter
            if not all_:
                return [ViewAdapter.craft_list_item(i, tasks_dict) for i in containers if tasks_dict[i].status == 2]
            return [ViewAdapter.craft_list_item(i, tasks_dict) for i in containers]
        except Exception:
            logging.exception('gRPC')
            return None

    def inspect(self, id_):
        try:
            q = containers_pb2.GetContainerRequest(id=id_)
            a = self._client.Get(q, metadata=(('containerd-namespace', self._namespace),)).container
            return ViewAdapter.craft_info(a, self._get_tasks_dict())

        except Exception:
            logging.exception('gRPC')
            return None

    def execute(self, id_, line_):
        exec_id = ''.join(random.choice(string.digits) for _ in range(8))
        return self._execute(["task", "exec", "--exec-id", exec_id, id_, '/bin/sh', '-c', line_])

    def query_usage(self, id_, last_cpu_, last_time_):
        # container_process_manager encode id to int
        # decoding it back
        i = format(id_, 'x').zfill(12).encode('UTF8')
        container_id = binascii.unhexlify(i).decode('UTF8')
        s = self.inspect(container_id)
        if not s:
            raise LookupError(container_id)

        def do_query():
            _, x = self._parse_metrics(["task", "metrics", container_id])
            if not x or len(x) == 0:
                return None
            return x

        return ContainerdContainerMemoryCpuUsage(last_cpu_, last_time_, do_query, container_id)
