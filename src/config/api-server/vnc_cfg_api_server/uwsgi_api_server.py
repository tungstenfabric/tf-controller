from gevent import monkey
monkey.patch_all()

import uwsgi
import api_server
pipe_start_app = None


def get_bottle_server():
    global pipe_start_app
    if pipe_start_app:
        return pipe_start_app
    worker_id = int(uwsgi.worker_id())
    if worker_id > 0:
        vnc_api_server = api_server.VncApiServer("-c /etc/contrail/contrail-api-%s.conf "
                                                 "-c /etc/contrail/contrail-keystone-auth.conf" %
                                                 (worker_id - 1))
    pipe_start_app = vnc_api_server.get_pipe_start_app()
    if pipe_start_app is None:
        pipe_start_app = vnc_api_server.api_bottle
    return pipe_start_app