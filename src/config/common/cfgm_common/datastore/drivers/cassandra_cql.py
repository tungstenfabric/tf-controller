#
# Copyright (c) 2020 Juniper Networks, Inc. All rights reserved.
#
import collections
import datetime
import importlib
import itertools
import math
from multiprocessing import cpu_count
from multiprocessing import Process
from multiprocessing.queues import Queue
import queue
import ssl
import sys

import gevent
import gevent.lock
from pysandesh.gen_py.process_info.ttypes import ConnectionStatus
from pysandesh.gen_py.sandesh.ttypes import SandeshLevel
from sandesh_common.vns import constants as vns_constants
import six
import six.moves

from cfgm_common import jsonutils as json
from cfgm_common import utils
from cfgm_common.datastore import api as datastore_api
from cfgm_common.exceptions import\
    DatabaseUnavailableError, NoIdError, VncError


try:
    connector = importlib.import_module('cassandra')
    connector.cluster = importlib.import_module('cassandra.cluster')
    connector.query = importlib.import_module('cassandra.query')
    connector.protocol = importlib.import_module('cassandra.protocol')
    connector.cqlengine = importlib.import_module('cassandra.cqlengine')
    connector.concurrent = importlib.import_module('cassandra.concurrent')
except ImportError:
    connector = None


DEFAULT_CQL_PORT = 9042
DEFAULT_THRIFT_PORT = 9160

# Properties passed to the column familly
TABLE_PROPERTIES = {
    'gc_grace_seconds': vns_constants.CASSANDRA_DEFAULT_GC_GRACE_SECONDS,
}

# Properties passed to the keyspaces
REPLICATION_PROPERTIES = {
    'class': 'SimpleStrategy',

    # None means it will be based to the number of node.
    'replication_factor': None,
}

# SSL related configurations
if sys.version_info >= (3, 6):
    # Python3.6 Introduces PROTOCOL_TLS which is using the best
    # version supported.
    SSL_VERSION = ssl.PROTOCOL_TLS
else:
    SSL_VERSION = ssl.PROTOCOL_TLSv1_2

# Set hard limit of the columns returned.
MAX_COLUMNS = 10000000

# Set default column cout for get_range
DEFAULT_COLUMN_COUNT = 100000

# Set number of rows per pages fetched
DEFAULT_PAGE_SIZE = None

# Set when to start loading aync execution
ASYNC_STARTS_WHEN = 1

# Using process workes to computes queries. This improve response-time
# by avoiding to block main process during large chunk of data to
# compute.
USE_WORKERS = True

# Number of workers used to execute SELECT queries
# TODO(sahid): Should be defined in config options.
NUM_WORKERS = cpu_count() / 2

# Max concurrent requests
EXECUTE_CONCURRENCY = 1024

# This limit the number of queries per batch.
BATCH_LIMIT = 1000

# String will be encoded in UTF-8 if necessary (Python2 support)
StringType = six.text_type

# Decodes JSON string in Python Object.
JsonToObject = json.loads

RowsResultType = collections.OrderedDict


# This is encapsulating the ResultSet iterator that to provide feature
# to filter the columns, decode JSON or add timestamp.
class Iter(six.Iterator):
    def __init__(self, result, columns,
                 include_timestamp=False,
                 decode_json=True,
                 logger=None,
                 num_columns=None,
                 cf_name="<noname>"):
        """Encapsulate results from Cassandra."""
        # Defines `columns` wanted. `columns_found` helps to track
        # the columns already discovered during iterate the
        # result so we can stop early.
        self.columns = columns and set(columns) or set([])
        self.num_columns = num_columns

        # Based on Pycassa ResultSet (legacy code) the results will be
        # of type {column: value} or {column: (value, timestamp)}
        self.include_timestamp = include_timestamp
        # When `True`, the JSON string in `value` will be decoded.
        self.decode_json = decode_json

        self.it = iter(result)

        # For debugging purpose
        self.logger = logger
        self.cf_name = cf_name

    __iter__ = lambda self: self
    __next__ = lambda self: self.next()

    def decode(self, v, k):
        if self.decode_json:
            try:
                v = JsonToObject(v)
            except (ValueError, TypeError) as e:
                # TODO(sahid): Imported from thrift's driver, we
                # should investigate and fix that problem.
                msg = ("can't decode JSON value, cf: '{}', key:'{}' "
                       "error: '{}'. Use it as it: '{}'".format(
                           self.cf_name, k, e, v))
                self.logger(msg, level=SandeshLevel.SYS_INFO)
        return v

    def timestamp(self, v, w):
        if self.include_timestamp:
            return (v, w)
        return v

    def format_value(self, v, w, k):
        return self.timestamp(self.decode(v, k), w)

    def next(self):
        if self.include_timestamp:
            # 0.column, 1.value, 2.timestamp
            dispatch = lambda k, r: (r[0], self.format_value(r[1], r[2], k))
        else:
            # 0.column, 1.value
            dispatch = lambda k, r: (r[0], self.decode(r[1], k))

        while(True):
            key, (success, results) = next(self.it)
            if not success:
                self.logger(
                    "Unable to get results for key='{}', error={}".format(
                        key, results),
                    level=SandeshLevel.SYS_WARN)
                continue
            columns_found = set([])
            rows = []
            for result in list(results):
                row = dispatch(key, result)

                column = row[0]
                if self.columns:
                    if column not in self.columns:
                        continue
                    columns_found.add(column)

                rows.append(row)

                if self.num_columns and len(rows) >= self.num_columns:
                    break

                if self.columns and self.columns == columns_found:
                    break
            return key, RowsResultType(rows)


# This is implementing our Cassandra API for the driver provided by
# DataStax, we try to stay simple, compatible with legacy, and finally
# compatible with Python2 as-well.  We have made the choice to avoid
# using the Object Mapping proposed by DataStax's driver to allow more
# flexibilities.  In a perfect world, any change here should be
# accompanied by an unittest to avoid regression.
class CassandraDriverCQL(datastore_api.CassandraDriver):

    def __init__(self, server_list, **options):
        """Start from here, please see API."""
        global connector
        if connector is None:
            raise ImportError("the CQL connector is not defined, can't "
                              "be null at this step. Please verify "
                              "dependencies.")
        super(CassandraDriverCQL, self).__init__(server_list, **options)

    # Options are defined here because they can be dinamic depending
    # external events/context, like the kind of queries, number of
    # nodes in Cassandra cluster...

    @property
    def SupportsPerPartitionLimit(self):
        # Only new version of Cassandra support it
        # TODO(sahid): Needs to determine which ones exaclty
        return False

    @property
    def AllowColumnsFiltering(self):
        # Filter columns from Cassandra, may be consuming.
        return True

    @property
    def InsertRemoveUsingBatch(self):
        # Always use batch to insert/remove multi columns.
        return False

    @property
    def FloodDuringDebug(self):
        # Accept debug message that can be floody.
        return False

    @property
    def ConsistencyLevel(self):
        # Setting that defines a successful write or read by the
        # number of cluster replicas that acknowledge the write or
        # respond to the read request, respectively. e.g: QUORUM #
        # ceil(RF/2) replicas must respond to consider the operation a
        # success
        return connector.ConsistencyLevel.QUORUM

    @property
    def BatchType(self):
        # Because we use `Batch` with queries within same CFs and
        # partition keys we can avoid writting LOG, that is improving
        # performance.
        return connector.query.BatchType.UNLOGGED

    @property
    def CqlVersion(self):
        # None means the best version supported by servers will be
        # used.
        return None

    @property
    def ProtocolVersions(self):
        # The connector will try to connect server from the higher
        # version to the lower. The minimun supported Cassandra is
        # 2.0.
        return (6, 5, 4, 3, 2)

    @property
    def BatchClass(self):
        # This is encapsulating `Batch` statement of DataStax
        # connector that to make it to have same behavior of `Batch`
        # type form pycassa which is what legacy is using. It also adds
        # checks related to performance like having a batch executed
        # for different partition key, or if executing for a same
        # partition key an insert/remove.
        class Batch(connector.query.BatchStatement):
            def __init__(self, context, cf_name):
                self.cf_name = cf_name
                self.partition_key = None
                self.action = None
                self.context = context
                super(Batch, self).__init__(
                    session=context.get_cf(cf_name),
                    consistency_level=self.context.ConsistencyLevel,
                    batch_type=self.context.BatchType)

            def logger(self, msg, level):
                if self.FloodDuringDebug:
                    self.options.logger(msg, level=level)

            def is_same_partition_key(self, partition_key):
                if self.partition_key is None:
                    self.partition_key = partition_key
                return self.partition_key == partition_key

            def is_same_action(self, action):
                if self.action is None:
                    self.action = action
                return self.action == action

            def add_insert(self, *args, **kwargs):
                return self.add("insert", *args, **kwargs)

            def add_remove(self, *args, **kwargs):
                return self.add("remove", *args, **kwargs)

            def add(self, action, partition_key, *args, **kwargs):
                """Add query to the batch."""
                if self.context.nodes() > 1 and\
                   not self.is_same_partition_key(partition_key):
                    self.logger("Adding in `batch` a query using "
                                "different partition keys, this implies "
                                "performance degration, commiting "
                                "current batch. (prev={}, new={})".format(
                                    self.partition_key, partition_key),
                                level=SandeshLevel.SYS_DEBUG)
                    self.send()
                    self.partition_key = partition_key
                elif not self.is_same_action(action):
                    self.logger("Adding in `batch` a query using "
                                "insert/delete with the same partition keys, "
                                "this is not supported by CQL (prev={}, "
                                "new={})".format(
                                    self.action, action),
                                level=SandeshLevel.SYS_DEBUG)
                    self.send()
                    self.action = action
                return super(Batch, self).add(*args, **kwargs)

            def send(self):
                """Commit batch and clear statement for new usage."""
                self._session.execute(self)
                self.clear()

        if self.__batch_class__ is None:
            self.__batch_class__ = Batch
        return self.__batch_class__

    __batch_class__ = None

    @property
    def RowFactory(self):
        return lambda c, r: r

    def create_cluster(self):
        # Authentication related options
        auth_provider = None
        if self.options.credential:
            auth_provider = connector.auth.PlainTextAuthProvider(
                username=self.options.credential.get('username'),
                password=self.options.credential.get('password'))

        # SSL related options
        ssl_options = None
        if self.options.ssl_enabled:
            # TODO(sahid): Future versions (>= 3.17) will support
            # ssl_context.
            ssl_options = {
                "ssl_version": SSL_VERSION,
                "ca_certs": self.options.ca_certs,
                "check_hostname": False,
                "cert_reqs": ssl.CERT_REQUIRED,
            }

        # Profiles related features
        ExecutionProfile = connector.cluster.ExecutionProfile
        profiles = {
            connector.cluster.EXEC_PROFILE_DEFAULT: ExecutionProfile(
                # TODO(sahid): Do we really want QUORUM when counting?
                consistency_level=self.ConsistencyLevel,
                row_factory=self.RowFactory,
                request_timeout=120,
            ),
        }

        # Addresses, ports related options
        endpoints, port = [], None
        for address in self._server_list:
            try:
                server, _port = address.split(':', 1)
                _port = int(_port)

                if port is not None:
                    if port != _port:
                        self.options.logger(
                            "Please consider fixing port for '{}', all "
                            "servers should have same port. "
                            "Using '{}'".format(
                                address, port), level=SandeshLevel.SYS_WARN)
                else:
                    port = _port

                endpoints.append(server)
            except ValueError:
                endpoints.append(address)

        # Best-effort to support upgrade from thrift to cql
        if port == DEFAULT_THRIFT_PORT:
            self.options.logger(
                "Usage of thrift port '{}' detected for CQL driver. "
                "Please consider fixing port number. Trying "
                "best-effort by switching to default port for "
                "CQL '{}'.".format(
                    DEFAULT_THRIFT_PORT,
                    DEFAULT_CQL_PORT),
                level=SandeshLevel.SYS_WARN)
            port = None

        connector.ProtocolVersion.SUPPORTED_VERSIONS = self.ProtocolVersions
        try:
            return connector.cluster.Cluster(
                endpoints,
                port=(port or DEFAULT_CQL_PORT),
                compression=True,
                ssl_options=ssl_options,
                auth_provider=auth_provider,
                execution_profiles=profiles,
                cql_version=self.CqlVersion)
        except Exception as error:
            raise DatabaseUnavailableError(
                "error, {}: {}".format(
                    error, utils.detailed_traceback()))

    def _Init_Cluster(self):
        self.report_status_init()

        self._cql_select = self._handle_exceptions(self._cql_select, 'SELECT')
        self._Insert = self._handle_exceptions(self._Insert, 'INSERT')
        self._Remove = self._handle_exceptions(self._Remove, 'REMOVE')
        self._Get_Range = self._handle_exceptions(self._Get_Range, 'RANGE')
        self._Get_Count = self._handle_exceptions(self._Get_Count, 'COUNT')

        self.lock = gevent.lock.Semaphore()

        self._cluster = self.create_cluster()
        self._cluster.connect()

        if USE_WORKERS:
            PoolClass = Pool
        else:
            PoolClass = DummyPool
        self.pool = PoolClass(
            NUM_WORKERS, self.worker, self.initializer)
        self.pool.prefork()

        # Initializes RW keyspaces
        for ks, cf_dict in self.options.rw_keyspaces.items():
            keyspace = self.keyspace(ks)
            if self.options.reset_config:
                self.safe_drop_keyspace(keyspace)
            self.safe_create_keyspace(keyspace)
            self.ensure_keyspace_replication(keyspace)

        # Ensures RO keyspaces are initialized
        while not self.are_keyspaces_ready(self.options.ro_keyspaces):
            self.options.logger("waiting for keyspaces '{}' to be ready "
                                "before to continue...".format(
                                    self.options.ro_keyspaces),
                                level=SandeshLevel.SYS_INFO)
            # Let's a chance to an other greenthread to be scheduled.
            gevent.sleep(1)

        # The CFs are flatten in a dict with the keyspaces' session
        # related.
        for ks, cf_dict in itertools.chain(
                self.options.rw_keyspaces.items(),
                self.options.ro_keyspaces.items()):
            for cf_name in cf_dict:
                self.create_session(self.keyspace(ks), cf_name)

        # Now we create the tables/CFs if not already alive.
        for cf_name in self._cf_dict:
            self.safe_create_table(cf_name)
            self.ensure_table_properties(cf_name)

        self.report_status_up()

    def _Create_Session(self, keyspace, cf_name, **cf_args):
        self._cf_dict[cf_name] = self._cluster.connect(
            keyspace)

    def _Column_Families(self, keyspace, prefixed=False):
        if not prefixed:
            keyspace = self.keyspace(keyspace)
        # TODO(sahid): I'm not able to find an easy way sofar.
        raise NotImplementedError

    def _Keyspace_Properties(self, keyspace):
        # TODO(sahid): I'm not able to find an easy way sofar.
        raise NotImplementedError

    def are_keyspaces_ready(self, keyspaces):
        """From a list of keyspaces, return False if one not yet available."""
        try:
            for ks, _ in keyspaces.items():
                self._cluster.connect(self.keyspace(ks))
        except connector.cluster.NoHostAvailable:
            return False
        return True

    def are_tables_ready(self, keyspace, tables):
        """From a list of tables, return False if one not yet available."""
        # TODO(sahid): Needs to be implemented
        return True

    def get_default_session(self):
        """Return the default session, not connected to any keyspace."""
        # It is a singleton, we don't have to worry whether the
        # session has already been created.
        return self._cluster.connect()

    def safe_create_table(self, cf_name):
        """Create table c.f ColumnFamilly if does not already exist."""
        ses = self.get_cf(cf_name)
        # We don't use IF EXISTS to print debug.
        cql = """
          CREATE TABLE "{}" (
            key blob,
            column1 blob,
            value text,
            PRIMARY KEY (key, column1)
          ) WITH COMPACT STORAGE AND CLUSTERING ORDER BY (column1 ASC)
          """.format(cf_name)
        try:
            ses.execute(cql)
            msg = "table '{}', created"
        except connector.protocol.AlreadyExists:
            msg = "table '{}', already created"
        self.options.logger(
            msg.format(cf_name), level=SandeshLevel.SYS_NOTICE)

    def ensure_table_properties(self, cf_name, props=TABLE_PROPERTIES):
        """Alter table to fix properties if necessary."""
        ses = self.get_cf(cf_name)
        cql = """
         ALTER TABLE "{}" WITH {}
        """.format(cf_name,
                   "AND ".join(
                       ["{}={} ".format(k, v) for k, v in props.items()]))
        ses.execute(cql)
        msg = "table '{}' fixed with properties {}"
        self.options.logger(
            msg.format(cf_name, props), level=SandeshLevel.SYS_NOTICE)

    def safe_drop_keyspace(self, keyspace):
        """Drop keyspace if exists."""
        ses = self.get_default_session()
        # We don't use IF EXISTS to print debug.
        cql = """
          DROP KEYSPACE "{}"
        """.format(keyspace)
        try:
            ses.execute(cql)
            msg = "keyspace '{}', dropped"
        except connector.protocol.ConfigurationException:
            msg = "keyspace '{}', already dropped or does not exist"
        self.options.logger(
            msg.format(keyspace), level=SandeshLevel.SYS_NOTICE)

    def safe_create_keyspace(self, keyspace, props=REPLICATION_PROPERTIES):
        """Create keyspace if does not already exist."""
        ses = self.get_default_session()
        # We don't use IF EXISTS to print debug.
        cql = """
          CREATE KEYSPACE "{}" WITH REPLICATION = {{
            'class': '{}',
            'replication_factor': '{}'
          }}
        """.format(keyspace,
                   props['class'],
                   # TODO(sahid): Considering using max 3
                   props['replication_factor'] or self.nodes())
        try:
            ses.execute(cql)
            msg = "keyspace '{}', created"
        except connector.protocol.AlreadyExists:
            msg = "keyspace '{}', already created"
        self.options.logger(
            msg.format(keyspace), level=SandeshLevel.SYS_NOTICE)

    def ensure_keyspace_replication(self, keyspace,
                                    props=REPLICATION_PROPERTIES):
        """Alter keyspace to fix replication."""
        ses = self.get_default_session()
        cql = """
          ALTER KEYSPACE "{}" WITH REPLICATION = {{
            'class': '{}',
            'replication_factor': '{}'
          }}
        """.format(keyspace,
                   props.get('class'),
                   # TODO(sahid): Considering using max 3
                   props.get('replication_factor') or self.nodes())
        ses.execute(cql)
        msg = "keyspace '{}' fixed with replication {}"
        self.options.logger(
            msg.format(keyspace, props), level=SandeshLevel.SYS_NOTICE)

    def initializer(self, worker_id):
        self._cluster = self.create_cluster()
        self._cluster.connect()

        # Ensures keyspaces/tables are ready before to continue
        while not self.are_keyspaces_ready(self.options.rw_keyspaces):
            gevent.sleep(0.5)
        for ks, cf_dict in six.iteritems(self.options.rw_keyspaces):
            keyspace = self.keyspace(ks)
            while not self.are_tables_ready(keyspace, six.viewkeys(cf_dict)):
                gevent.sleep(0.5)
        while not self.are_keyspaces_ready(self.options.ro_keyspaces):
            gevent.sleep(0.5)

        self._cf_dict = {}
        for ks, cf_dict in itertools.chain(
                self.options.rw_keyspaces.items(),
                self.options.ro_keyspaces.items()):
            for cf_name in cf_dict:
                self.create_session(self.keyspace(ks), cf_name)

    def worker(self, worker_id, args, params):
        (cql, cf_name, columns, include_timestamp,
         decode_json, num_columns) = params
        ses = self.get_cf(cf_name)

        if decode_json is None:
            # Only the CFs related to UUID_KEYSPACE_NAME's keyspace
            # encode its column values to JSON we want decode them
            # automatically.
            decode_json = ses.keyspace.endswith(
                datastore_api.UUID_KEYSPACE_NAME)

        columns = columns if not self.AllowColumnsFiltering else None
        keys = [a[0] for a in args]

        req = self.apply(ses, cql, args)
        req = zip(keys, req)
        req = Iter(req,
                   # We currently still use Cassandra to filter
                   # columns. IT may be better to dispatch the filter
                   # in several cores on application
                   columns=columns,
                   include_timestamp=include_timestamp,
                   decode_json=decode_json,
                   num_columns=num_columns,
                   logger=self.options.logger,
                   cf_name=cf_name)
        return list(req)

    def _cql_select(self, cf_name, keys, start='', finish='', num_columns=None,
                    columns=None, include_timestamp=False, decode_json=None):
        cql = """
        SELECT blobAsText(column1), value{}
        FROM "{}"
        WHERE key = textAsBlob(%s)
        """.format(
            include_timestamp and ", WRITETIME(value)" or "", cf_name)
        if self.AllowColumnsFiltering and columns:
            cql += "AND column1 IN ({}) ".format(
                ", ".join(["textAsBlob(%s)"] * len(columns)))
        if start:
            cql += "AND column1 >= textAsBlob(%s) "
        if finish:
            cql += "AND column1 <= textAsBlob(%s) "
        if self.SupportsPerPartitionLimit and num_columns:
            cql += "PER PARTITION LIMIT %s "
        if self.AllowColumnsFiltering and columns:
            # Consuming for Cassandra, but we are I/O bounding in
            # Python because of gevent.
            cql += "ALLOW FILTERING"

        args = []
        for key in keys:
            arg = [StringType(key)]
            if self.AllowColumnsFiltering and columns:
                arg += [StringType(x) for x in columns]
            if start:
                arg.append(StringType(start))
            if finish:
                arg.append(StringType(finish))
            if self.SupportsPerPartitionLimit and num_columns:
                arg.append(num_columns)
            args.append(arg)

        req = self.pool.compute(args,
                                cql,
                                cf_name,
                                columns,
                                include_timestamp,
                                decode_json,
                                num_columns)
        return req

    def _Get_CF_Batch(self, cf_name, keyspace_name=None):
        return self.BatchClass(context=self, cf_name=cf_name)

    def _Multiget(self, cf_name, keys, columns=None, start='', finish='',
                  timestamp=False, num_columns=None):
        try:
            num_columns = max(int(num_columns), num_columns)
        except (ValueError, TypeError):
            num_columns = MAX_COLUMNS
        if num_columns == MAX_COLUMNS:
            num_columns = None

        if not keys:
            # It seems that it happens we query with empty list.
            return {}

        results = {}
        for key, rows in self._cql_select(
                cf_name, keys=keys, start=start, finish=finish,
                columns=columns, include_timestamp=timestamp,
                num_columns=num_columns):
            if rows:
                results[key] = rows

        wanted, received = len(keys), len(results)
        if wanted != received:
            missing = keys - six.viewkeys(results)
            self.options.logger(
                "Inconsistency discovered. wanted={}, received={}, "
                "missing={}. This may indicate that the cluster needs a "
                "'nodetool repair'.".format(
                    wanted, received, missing),
                level=SandeshLevel.SYS_WARN)

        return results

    def _XGet(self, cf_name, key, columns=None, start='', finish=''):
        rows = self._Get(
            cf_name=cf_name,
            key=key,
            start=start,
            finish=finish,
            columns=columns,
            _decode_json=False)
        return six.iteritems(rows or {})

    def _Get(self, cf_name, key, columns=None, start='', finish='',
             # XGet never wants auto-decode json. TODO(sahid): fix
             # base-code to be coherent.
             _decode_json=None):
        for _, rows in self._cql_select(
                cf_name=cf_name,
                keys=[key],
                start=start,
                finish=finish,
                columns=columns,
                decode_json=_decode_json):
            return rows

    def _Get_One_Col(self, cf_name, key, column):
        rows = self._Get(
            cf_name=cf_name,
            key=key,
            columns=[column])
        if not rows:
            raise NoIdError(key)
        return rows[column]

    def _Get_Range(self, cf_name, columns=None,
                   column_count=DEFAULT_COLUMN_COUNT,
                   include_timestamp=False):
        ses = self.get_cf(cf_name)
        arg, cql = [], """
        SELECT blobAsText(key), blobAsText(column1), value{}
        FROM "{}"
        """.format(
            include_timestamp and ", WRITETIME(value)" or "", cf_name)

        if self.AllowColumnsFiltering and columns:
            cql += "WHERE column1 IN ({}) ".format(
                ", ".join(["textAsBlob(%s)"] * len(columns)))
            arg += [StringType(x) for x in columns]
        if self.SupportsPerPartitionLimit:
            if column_count and column_count != DEFAULT_COLUMN_COUNT:
                cql += "PER PARTITION LIMIT %s "
                arg.append(column_count)
        if self.AllowColumnsFiltering and columns:
            cql += "ALLOW FILTERING"

        def treat(current_key, aggregator):
            for k, rows in Iter([(current_key, (True, aggregator))],
                                columns=(columns
                                         if not self.AllowColumnsFiltering
                                         else None),
                                include_timestamp=include_timestamp,
                                decode_json=False,
                                logger=self.options.logger,
                                num_columns=column_count,
                                cf_name=cf_name):
                yield k, rows

        current_key, aggregator = None, []
        for row in ses.execute(cql, arg):
            key, row = row[0], row[1:]

            if current_key is None:
                current_key = key

            if current_key == key:
                aggregator.append(row)
            else:
                for k, rows in treat(current_key, aggregator):
                    yield k, rows

                current_key = key
                aggregator = [row]

        # Handle last rows
        for k, rows in treat(current_key, aggregator):
            yield k, rows

    def _Get_Count(self, cf_name, key, start='', finish='',
                   keyspace_name=None):
        ses = self.get_cf(cf_name)
        arg, cql = [], """
          SELECT COUNT(*) FROM "{}"
          WHERE key = textAsBlob(%s)
        """.format(cf_name)
        arg = [StringType(key)]
        if start:
            cql += "AND column1 >= textAsBlob(%s) "
            arg.append(StringType(start))
        if finish:
            cql += "AND column1 <= textAsBlob(%s) "
            arg.append(StringType(finish))
        return ses.execute(cql, arg).one()[0]

    def _Insert(self, key, columns, keyspace_name=None, cf_name=None,
                batch=None, column_family=None):
        if cf_name is None and batch is None:
            raise VncError("one of cf_name or batch args "
                           "should be provided to insert {} for {}".format(
                               columns, key))
        if column_family:
            raise VncError("driver does not support column_family's arg "
                           "to insert {} for {}".format(columns, key))
        if batch is not None:
            cf_name = batch.cf_name

        local_batch = False
        if self.InsertRemoveUsingBatch and batch is None:
            batch = self.get_cf_batch(cf_name)
            local_batch = True

        ses = self.get_cf(cf_name)
        cql = """
          INSERT INTO "{}"
          (key, column1, value)
          VALUES (textAsBlob(%s), textAsBlob(%s), %s)
        """.format(cf_name)

        if batch is not None:
            for column, value in columns.items():
                if len(batch) >= BATCH_LIMIT:
                    batch.send()
                batch.add_insert(key, cql, [StringType(key),
                                            StringType(column),
                                            StringType(value)])
            if local_batch:
                batch.send()
        else:
            self._cql_execute(ses, cql, key, columns)

    def _cql_execute(self, ses, cql, key, columns):
        args = []
        if isinstance(columns, dict):
            # Case of insert {column: value}
            for column, value in six.iteritems(columns):
                args.append([StringType(key),
                             StringType(column),
                             StringType(value)])
        else:
            # Case of remove [column, ...]
            for column in columns:
                args.append([StringType(key),
                             StringType(column)])
        self.apply(ses, cql, args)

    def apply(self, ses, cql, args):
        if len(args) <= ASYNC_STARTS_WHEN:
            return [(True, ses.execute(cql, arg)) for arg in args]
        return connector.concurrent.execute_concurrent_with_args(
            ses, cql, args, concurrency=EXECUTE_CONCURRENCY)

    def _Remove(self, key, columns=None, keyspace_name=None, cf_name=None,
                batch=None, column_family=None):
        if cf_name is None and batch is None:
            raise VncError("one of cf_name or batch args "
                           "should be provided to remove {} for {}".format(
                               columns, key))
        if column_family:
            raise VncError("driver does not support column_family's arg "
                           "to remove {} for {}".format(columns, key))
        if batch is not None:
            cf_name = batch.cf_name

        local_batch = False
        if self.InsertRemoveUsingBatch and batch is None:
            batch = self.get_cf_batch(cf_name)
            local_batch = True

        ses = self.get_cf(cf_name)
        if not columns:
            cql = """
              DELETE FROM "{}"
              WHERE key = textAsBlob(%s)
            """.format(cf_name)
            if batch is not None:
                if len(batch) >= BATCH_LIMIT:
                    batch.send()
                batch.add_remove(key, cql, [StringType(key)])
            else:
                ses.execute(cql, [StringType(key)])
        else:
            cql = """
              DELETE FROM "{}"
              WHERE key = textAsBlob(%s)
              AND column1 = textAsBlob(%s)
            """.format(cf_name)
            if batch is not None:
                for column in columns:
                    batch.add_remove(key, cql, [StringType(key),
                                                StringType(column)])
                if local_batch:
                    batch.send()
            else:
                self._cql_execute(ses, cql, key, columns)

    # TODO(sahid): Backward compatible function from thrift's driver.
    # Do we really need this?
    def _handle_exceptions(self, func, oper=None):
        def wrapper(*args, **kwargs):
            try:
                if self.get_status() != ConnectionStatus.UP:
                    self._Init_Cluster()
                self.start_time = datetime.datetime.now()
                return func(*args, **kwargs)
            except (connector.InvalidRequest,
                    connector.cluster.NoHostAvailable,
                    connector.cqlengine.CQLEngineException) as e:
                if self.get_status() != ConnectionStatus.DOWN:
                    self.report_status_down()
                    self.options.logger(
                        "Cassandra connection down. Exception in {}".format(
                            func), level=SandeshLevel.SYS_ERR)
                raise DatabaseUnavailableError(
                    "error, {}: {}".format(
                        e, utils.detailed_traceback()))
            finally:
                if ((self.log_response_time) and (oper)):
                    self.end_time = datetime.datetime.now()
                    self.log_response_time(
                        self.end_time - self.start_time, oper)
        return wrapper


# A cooperative queue with gevent
class CoopQueue(Queue):
    def get(self):
        while True:
            try:
                return super(CoopQueue, self).get(False)
            except queue.Empty:
                pass
            gevent.sleep(0.01)


# This is implementing a pool of processes that will execute SELECT
# queries. That because for large dataset it takes more time to decode
# the result than getting it from Cassandra. Since we are gevent
# based, blocking the main process with CPU executions is blocking
# schelduling of greenthreads which implies performances-degradation.
class Pool(object):
    def __init__(self, num_workers, target, initializer):
        self.num_workers = num_workers
        self.target = target
        self.initializer = initializer
        self.workers = []
        self.lock = gevent.lock.Semaphore()

    def prefork(self):
        for i in six.moves.xrange(self.num_workers):
            qin, qout = CoopQueue(), CoopQueue()

            def my_loop():
                gevent.reinit()
                hub = gevent.get_hub()
                del hub.threadpool
                hub._threadpool = None
                hub.destroy(destroy_loop=True)
                h = gevent.get_hub(default=True)

                self.initializer(i)
                try:
                    for args, params in iter(qin.get, 'STOP'):
                        qout.put(self.target(i, args, params))
                except KeyboardInterrupt:
                    pass

            p = Process(target=my_loop)
            p.daemon = True
            p.start()
            self.workers.append((p, qin, qout))

    def compute(self, args, *append_args):
        self.lock.acquire()
        size = math.ceil(len(args) / float(self.num_workers)) or 1
        group = []
        for i, n in enumerate(six.moves.xrange(0, len(args), size)):
            _, qin, _ = self.workers[i]
            qin.put((args[n:n + size], append_args))
            group.append(i)
        response = []
        for i in group:
            _, _, qout = self.workers[i]
            response.append(qout.get())
        result = list(itertools.chain(*response))
        self.lock.release()
        return result


class DummyPool(Pool):

    def prefork(self):
        pass

    def compute(self, args, *append_args):
        return self.target(0, args, append_args)
