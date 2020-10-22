import bottle
import uwsgi
import api_server
from gevent import monkey
monkey.patch_all()


def get_apiserver():
    worker_id = int(uwsgi.worker_id())
    if worker_id > 0:
        vnc_api_server = api_server.VncApiServer(
            " -c /etc/contrail/contrail-api-%s.conf"
            " -c /etc/contrail/contrail-keystone-auth.conf" %
            (worker_id - 1))

    @vnc_api_server.api_bottle.hook('before_request')
    def check_db_resync_status():
        try:
            err_msg = "Api server is Initializing:DB Resync in progress"
            if not vnc_api_server._db_conn._db_resync_done.isSet():
                raise bottle.HTTPError(503, err_msg)
        except NameError:
            raise bottle.HTTPError(503, err_msg)

    pipe_start_app = vnc_api_server.get_pipe_start_app()
    if pipe_start_app is None:
        pipe_start_app = vnc_api_server.api_bottle
    return pipe_start_app
