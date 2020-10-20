from __future__ import unicode_literals

from cfgm_common.uve.config_updater import ttypes as config_update

bool_int_map = {1: True, 0: False}
# Class that handles backend of updating config parameters
class ConfigUpdater(object):
    _api_server_obj = None

    @staticmethod
    def register_config_update_handler(api_server_obj):
        config_update.ConfigApiUpdateReq.handle_request = \
            ConfigUpdater.config_update_var_handle_request
        ConfigUpdater._api_server_obj = api_server_obj

    @classmethod
    def config_update_var_handle_request(cls, req):
        # get the value of curring logging flags
        if req.enable_api_stats_log is not None:
            update_vnc_api_stats_log = bool_int_map[req.enable_api_stats_log]
            setattr(
                ConfigUpdater._api_server_obj, 'enable_api_stats_log',
                update_vnc_api_stats_log
            )

        if req.enable_latency_stats_log is not None:
            update_latency_stats_log = \
                bool_int_map[req.enable_latency_stats_log]
            setattr(
                ConfigUpdater._api_server_obj, 'enable_latency_stats_log',
                update_latency_stats_log
            )

        config_update_resp = config_update.ConfigApiUpdateResp(
            enable_api_stats_log=getattr(
                ConfigUpdater._api_server_obj, 'enable_api_stats_log'),
            enable_latency_stats_log=getattr(
                ConfigUpdater._api_server_obj, 'enable_latency_stats_log')
        )

        config_update_resp.response(req.context())
