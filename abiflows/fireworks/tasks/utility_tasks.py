# coding: utf-8
"""
Utility tasks for Fireworks.
"""

from __future__ import print_function, division, unicode_literals

from fireworks.core.firework import Firework, FireTaskBase, FWAction
from fireworks.core.launchpad import LaunchPad
from fireworks.utilities.fw_utilities import explicit_serialize
from fireworks.utilities.fw_serializers import serialize_fw

import os
import shutil
import logging
import traceback
import importlib
from abiflows.fireworks.tasks.abinit_tasks import INDIR_NAME, OUTDIR_NAME, TMPDIR_NAME
from abiflows.fireworks.utils.databases import MongoDatabase
from monty.serialization import loadfn
from monty.json import jsanitize


logger = logging.getLogger(__name__)


@explicit_serialize
class FinalCleanUpTask(FireTaskBase):

    def __init__(self, out_exts=None):
        if out_exts is None:
            out_exts = ["WFK", "1WF"]
        if isinstance(out_exts, str):
            out_exts = [s.strip() for s in out_exts.split(',')]

        self.out_exts = out_exts

    @serialize_fw
    def to_dict(self):
        return dict(out_exts=self.out_exts)

    @classmethod
    def from_dict(cls, m_dict):
        return cls(out_exts=m_dict['out_exts'])

    @staticmethod
    def delete_files(d, exts=None):
        deleted_files = []
        if os.path.isdir(d):
            for f in os.listdir(d):
                if exts is None or "*" in exts or any(ext in f for ext in exts):
                    fp = os.path.join(d, f)
                    try:
                        if os.path.isfile(fp):
                            os.unlink(fp)
                        elif os.path.isdir(fp):
                            shutil.rmtree(fp)
                        deleted_files.append(fp)
                    except:
                        logger.warning("Couldn't delete {}: {}".format(fp, traceback.format_exc()))

        return deleted_files

    def run_task(self, fw_spec):
        # the FW.json/yaml file is mandatory to get the fw_id
        # no need to deserialize the whole FW
        try:
            fw_dict = loadfn('FW.json')
        except IOError:
            try:
                fw_dict = loadfn('FW.yaml')
            except IOError:
                raise RuntimeError("No FW.json nor FW.yaml file present: impossible to determine fw_id")

        fw_id = fw_dict['fw_id']
        lp = LaunchPad.auto_load()
        wf = lp.get_wf_by_fw_id_lzyfw(fw_id)

        deleted_files = []
        # iterate over all the fws and launches
        for fw_id, fw in wf.id_fw.items():
            for l in fw.launches+fw.archived_launches:
                l_dir = l.launch_dir

                deleted_files.extend(self.delete_files(os.path.join(l_dir, TMPDIR_NAME)))
                deleted_files.extend(self.delete_files(os.path.join(l_dir, INDIR_NAME)))
                deleted_files.extend(self.delete_files(os.path.join(l_dir, OUTDIR_NAME), self.out_exts))

        logging.info("Deleted files:\n {}".format("\n".join(deleted_files)))

        return FWAction(stored_data={'deleted_files': deleted_files})


@explicit_serialize
class DatabaseInsertTask(FireTaskBase):

    def __init__(self, insertion_data=None, criteria=None):
        if insertion_data is None:
            insertion_data = {'structure': 'get_final_structure_and_history'}
        self.insertion_data = insertion_data
        self.criteria = criteria

    @serialize_fw
    def to_dict(self):
        return dict(insertion_data=self.insertion_data, criteria=self.criteria)

    @classmethod
    def from_dict(cls, m_dict):
        return cls(insertion_data=m_dict['insertion_data'],
                   criteria=m_dict['criteria'] if 'criteria' in m_dict else None)

    @staticmethod
    def insert_objects():
        return None

    def run_task(self, fw_spec):
        # the FW.json/yaml file is mandatory to get the fw_id
        # no need to deserialize the whole FW
        try:
            fw_dict = loadfn('FW.json')
        except IOError:
            try:
                fw_dict = loadfn('FW.yaml')
            except IOError:
                raise RuntimeError("No FW.json nor FW.yaml file present: impossible to determine fw_id")

        fw_id = fw_dict['fw_id']
        lp = LaunchPad.auto_load()
        wf = lp.get_wf_by_fw_id(fw_id)
        wf_module = importlib.import_module(wf.metadata['workflow_module'])
        wf_class = getattr(wf_module, wf.metadata['workflow_class'])

        database = MongoDatabase.from_dict(fw_spec['mongo_database'])
        if self.criteria is not None:
            entry = database.get_entry(criteria=self.criteria)
        else:
            entry = {}

        inserted = []
        for root_key, method_name in self.insertion_data.items():
            get_results_method = getattr(wf_class, method_name)
            results = get_results_method(wf)
            for key, val in results.items():
                entry[key] = jsanitize(val)
                inserted.append(key)

        if self.criteria is not None:
            database.save_entry(entry=entry)
        else:
            database.insert_entry(entry=entry)

        logging.info("Inserted data:\n{}".format('- {}\n'.join(inserted)))
        return FWAction()
