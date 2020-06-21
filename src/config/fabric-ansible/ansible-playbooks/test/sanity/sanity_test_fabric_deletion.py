#!/usr/bin/python

#
# Copyright (c) 2013 Juniper Networks, Inc. All rights reserved.
#

"""
This file contains sanity test for all major workflows supported by
fabric ansible
"""
from __future__ import absolute_import

from builtins import str
from .sanity_base import SanityBase
from . import config


# pylint: disable=E1101
class SanityTestFabricDeletion(SanityBase):
    """
    Sanity test on fabric deletion
    """

    def __init__(self, cfg):
        SanityBase.__init__(self, cfg, 'sanity_test_fabric_deletion')
    # end __init__

    def delete_fabric(self, fabric_name):
        """delete fabric and all objects in it"""
        self._logger.info("Delete fabric ...")
        job_template_fq_name = [
            'default-global-system-config', 'fabric_deletion_template']
        fabric_fq_name = [
            'default-global-system-config', fabric_name]

        job_execution_info = self._api.execute_job(
            job_template_fq_name=job_template_fq_name, 
            job_input={
                "fabric_fq_name": fabric_fq_name
            }
        )
        job_execution_id = job_execution_info.get('job_execution_id')
        self._logger.debug(
            "fabric deletion job started with execution id: %s", job_execution_id)
        self._wait_and_display_job_progress('fabric deletion',
                                            job_execution_id, fabric_fq_name,
                                            job_template_fq_name)
        self._logger.info("... Fabric deletion complete")
    # end delete_fabric

    def test(self):
        try:
            self.delete_fabric('fab01')
        except Exception as ex:
            self._exit_with_error(
                "Test failed due to unexpected error: %s" % str(ex))
    # end test


if __name__ == "__main__":
    SanityTestFabricDeletion(config.load('sanity/config/test_config.yml')).test()
# end __main__
