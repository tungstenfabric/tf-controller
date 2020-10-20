from __future__ import unicode_literals

from cfgm_common.uve.config_updater import ttypes as config_update


# Class that handles backend of updating config parameters
class ConfigUpdater(object):
    _api_server_obj = None
    bool_int_map = {1: True, 0: False}
    # setup response with default variables
    config_vars = {
        'enable_api_stats_log': False,
        'enable_latency_stats_log': False}

    @staticmethod
    def register_config_update_handler(api_server_obj):
        config_update.ConfigApiUpdateReq.handle_request = \
            ConfigUpdater.config_update_var_handle_request
        ConfigUpdater._api_server_obj = api_server_obj

    @classmethod
    def update_api_server_obj(cls, var_name, var_value):
        setattr(cls._api_server_obj, var_name, var_value)

    @classmethod
    def process_enable_api_stats_log(cls, req):
        if req.enable_api_stats_log is not None:
            update_vnc_api_stats_log = (
                cls.bool_int_map[req.enable_api_stats_log])
            cls.update_api_server_obj(
                'enable_api_stats_log', update_vnc_api_stats_log)
            cls.config_vars['enable_api_stats_log'] = update_vnc_api_stats_log

    @classmethod
    def process_enable_latency_stats_log(cls, req):
        if req.enable_latency_stats_log is not None:
            update_latency_stats_log = (
                cls.bool_int_map[req.enable_latency_stats_log])
            cls.update_api_server_obj(
                'enable_latency_stats_log', update_latency_stats_log)
            cls.config_vars['enable_latency_stats_log'] = (
                update_latency_stats_log)

    @classmethod
    def config_update_var_handle_request(cls, req):
        # process all variables
        cls.process_enable_api_stats_log(req)
        cls.process_enable_latency_stats_log(req)

        # respond back to config update call
        config_update_resp = config_update.ConfigApiUpdateResp(
            **cls.config_vars)
        config_update_resp.response(req.context())
