import pytest
import signal
import testinfra
from iterators import TimeoutIterator
import re

from helpers import get_app_home, get_app_install_dir, get_bootstrap_proc, get_procs, \
    parse_properties, parse_xml, run_image, \
    wait_for_http_response, wait_for_proc, wait_for_state, wait_for_log

PORT = 8090
STATUS_URL = f'http://localhost:{PORT}/status'


def test_jvm_args(docker_cli, image, run_user):
    environment = {
        'JVM_MINIMUM_MEMORY': '383m',
        'JVM_MAXIMUM_MEMORY': '2047m',
        'JVM_RESERVED_CODE_CACHE_SIZE': '383m',
        'JVM_SUPPORT_RECOMMENDED_ARGS': '-verbose:gc',
    }
    container = run_image(docker_cli, image, user=run_user, environment=environment)
    _jvm = wait_for_proc(container, get_bootstrap_proc(container))

    procs_list = get_procs(container)
    jvm = [proc for proc in procs_list if get_bootstrap_proc(container) in proc][0]

    assert f'-Xms{environment.get("JVM_MINIMUM_MEMORY")}' in jvm
    assert f'-Xmx{environment.get("JVM_MAXIMUM_MEMORY")}' in jvm
    assert f'-XX:ReservedCodeCacheSize={environment.get("JVM_RESERVED_CODE_CACHE_SIZE")}' in jvm
    assert environment.get('JVM_SUPPORT_RECOMMENDED_ARGS') in jvm


def test_install_permissions(docker_cli, image):
    container = run_image(docker_cli, image)

    assert container.file(f'{get_app_install_dir(container)}').user == 'root'

    for d in ['logs', 'work', 'temp']:
        path = f'{get_app_install_dir(container)}/{d}'
        assert container.file(path).user == 'confluence'


def test_first_run_state(docker_cli, image, run_user):
    container = run_image(docker_cli, image, user=run_user, ports={PORT: PORT})

    wait_for_http_response(STATUS_URL, expected_status=200, expected_state=('STARTING', 'FIRST_RUN'), max_wait=120)


def test_clean_shutdown(docker_cli, image, run_user):
    container = docker_cli.containers.run(image, detach=True, user=run_user, ports={PORT: PORT})
    host = testinfra.get_host("docker://"+container.id)
    wait_for_state(STATUS_URL, expected_state='FIRST_RUN')

    container.kill(signal.SIGTERM)

    end = r'org\.apache\.coyote\.AbstractProtocol\.destroy Destroying ProtocolHandler'
    wait_for_log(container, end)


def test_shutdown_script(docker_cli, image, run_user):
    container = docker_cli.containers.run(image, detach=True, user=run_user, ports={PORT: PORT})
    host = testinfra.get_host("docker://"+container.id)
    wait_for_state(STATUS_URL, expected_state='FIRST_RUN')

    container.exec_run('/shutdown-wait.sh')

    end = r'org\.apache\.coyote\.AbstractProtocol\.destroy Destroying ProtocolHandler'
    wait_for_log(container, end)


def test_server_xml_defaults(docker_cli, image):
    container = run_image(docker_cli, image)
    _jvm = wait_for_proc(container, get_bootstrap_proc(container))

    xml = parse_xml(container, f'{get_app_install_dir(container)}/conf/server.xml')
    connector = xml.find('.//Connector')
    context = xml.find('.//Context')

    assert connector.get('port') == '8090'
    assert connector.get('maxThreads') == '48'
    assert connector.get('minSpareThreads') == '10'
    assert connector.get('connectionTimeout') == '20000'
    assert connector.get('enableLookups') == 'false'
    assert connector.get('protocol') == 'org.apache.coyote.http11.Http11NioProtocol'
    assert connector.get('redirectPort') == '8443'
    assert connector.get('acceptCount') == '10'
    assert connector.get('debug') == '0'
    assert connector.get('URIEncoding') == 'UTF-8'
    assert connector.get('secure') == 'false'
    assert connector.get('scheme') == 'http'
    assert connector.get('proxyName') == ''
    assert connector.get('proxyPort') == ''
    assert connector.get('maxHttpHeaderSize') == '8192'

    assert context.get('path') == ''

def test_server_xml_catalina_fallback(docker_cli, image):
    environment = {
        'CATALINA_CONNECTOR_PROXYNAME': 'PROXYNAME',
        'CATALINA_CONNECTOR_PROXYPORT': 'PROXYPORT',
        'CATALINA_CONNECTOR_SECURE': 'SECURE',
        'CATALINA_CONNECTOR_SCHEME': 'SCHEME',
        'CATALINA_CONTEXT_PATH': 'CONTEXT'
    }
    container = run_image(docker_cli, image, environment=environment)
    _jvm = wait_for_proc(container, get_bootstrap_proc(container))

    xml = parse_xml(container, f'{get_app_install_dir(container)}/conf/server.xml')
    connector = xml.find('.//Connector')
    context = xml.find('.//Context')

    assert connector.get('proxyName') == 'PROXYNAME'
    assert connector.get('proxyPort') == 'PROXYPORT'
    assert connector.get('scheme') == 'SCHEME'
    assert connector.get('secure') == 'SECURE'
    assert context.get('path') == 'CONTEXT'


def test_server_xml_params(docker_cli, image):
    environment = {
        'ATL_TOMCAT_MGMT_PORT': '8006',
        'ATL_TOMCAT_PORT': '9090',
        'ATL_TOMCAT_MAXTHREADS': '201',
        'ATL_TOMCAT_MINSPARETHREADS': '11',
        'ATL_TOMCAT_CONNECTIONTIMEOUT': '20001',
        'ATL_TOMCAT_ENABLELOOKUPS': 'true',
        'ATL_TOMCAT_PROTOCOL': 'HTTP/2',
        'ATL_TOMCAT_REDIRECTPORT': '8444',
        'ATL_TOMCAT_ACCEPTCOUNT': '11',
        'ATL_TOMCAT_DEBUG': '1',
        'ATL_TOMCAT_URIENCODING':'ISO-8859-1',
        'ATL_TOMCAT_SECURE': 'true',
        'ATL_TOMCAT_SCHEME': 'https',
        'ATL_PROXY_NAME': 'conf.atlassian.com',
        'ATL_PROXY_PORT': '443',
        'ATL_TOMCAT_MAXHTTPHEADERSIZE': '8193',
        'ATL_TOMCAT_CONTEXTPATH': '/myconf',
    }
    container = run_image(docker_cli, image, environment=environment)
    _jvm = wait_for_proc(container, get_bootstrap_proc(container))

    xml = parse_xml(container, f'{get_app_install_dir(container)}/conf/server.xml')
    connector = xml.find('.//Connector')
    context = xml.find('.//Context')

    assert xml.get('port') == environment.get('ATL_TOMCAT_MGMT_PORT')

    assert connector.get('port') == environment.get('ATL_TOMCAT_PORT')
    assert connector.get('maxThreads') == environment.get('ATL_TOMCAT_MAXTHREADS')
    assert connector.get('minSpareThreads') == environment.get('ATL_TOMCAT_MINSPARETHREADS')
    assert connector.get('connectionTimeout') == environment.get('ATL_TOMCAT_CONNECTIONTIMEOUT')
    assert connector.get('enableLookups') == environment.get('ATL_TOMCAT_ENABLELOOKUPS')
    assert connector.get('protocol') == environment.get('ATL_TOMCAT_PROTOCOL')
    assert connector.get('redirectPort') == environment.get('ATL_TOMCAT_REDIRECTPORT')
    assert connector.get('acceptCount') == environment.get('ATL_TOMCAT_ACCEPTCOUNT')
    assert connector.get('debug') == environment.get('ATL_TOMCAT_DEBUG')
    assert connector.get('URIEncoding') == environment.get('ATL_TOMCAT_URIENCODING')
    assert connector.get('secure') == environment.get('ATL_TOMCAT_SECURE')
    assert connector.get('scheme') == environment.get('ATL_TOMCAT_SCHEME')
    assert connector.get('proxyName') == environment.get('ATL_PROXY_NAME')
    assert connector.get('proxyPort') == environment.get('ATL_PROXY_PORT')
    assert connector.get('maxHttpHeaderSize') == environment.get('ATL_TOMCAT_MAXHTTPHEADERSIZE')

    assert context.get('path') == environment.get('ATL_TOMCAT_CONTEXTPATH')

def test_server_xml_access_log_enabled(docker_cli, image):
    environment = {
        'ATL_TOMCAT_ACCESS_LOG': 'true',
        'ATL_TOMCAT_PROXY_INTERNAL_IPS': '192.168.1.1',
        'CONFLUENCE_VERSION': '7.10.0',
    }

    container = run_image(docker_cli, image, environment=environment)
    _jvm = wait_for_proc(container, get_bootstrap_proc(container))

    xml = parse_xml(container, f'{get_app_install_dir(container)}/conf/server.xml')
    value = xml.find('.//Context/Valve[@className="org.apache.catalina.valves.RemoteIpValve"]')
    assert value.get('internalProxies') == environment.get('ATL_TOMCAT_PROXY_INTERNAL_IPS')

def test_server_xml_access_log_disabled(docker_cli, image):
    environment = {
        'ATL_TOMCAT_ACCESS_LOG': 'false',
        'ATL_TOMCAT_PROXY_INTERNAL_IPS': '192.168.1.1',
        'CONFLUENCE_VERSION': '7.12.0',
    }

    container = run_image(docker_cli, image, environment=environment)
    _jvm = wait_for_proc(container, get_bootstrap_proc(container))

    xml = parse_xml(container, f'{get_app_install_dir(container)}/conf/server.xml')
    value = xml.find('.//Context/Valve[@className="org.apache.catalina.valves.RemoteIpValve"]')
    assert value is None

def test_server_xml_access_log_default_ver_lt_7_11(docker_cli, image):
    environment = {
        #'ATL_TOMCAT_ACCESS_LOG': Not defined,
        'ATL_TOMCAT_PROXY_INTERNAL_IPS': '192.168.1.1',
        'CONFLUENCE_VERSION': "7.10.0",
    }

    container = run_image(docker_cli, image, environment=environment)
    _jvm = wait_for_proc(container, get_bootstrap_proc(container))

    xml = parse_xml(container, f'{get_app_install_dir(container)}/conf/server.xml')
    value = xml.find('.//Context/Valve[@className="org.apache.catalina.valves.RemoteIpValve"]')
    assert value is None

def test_server_xml_access_log_default_ver_gt_7_11(docker_cli, image):
    environment = {
        #'ATL_TOMCAT_ACCESS_LOG': Not defined,
        'ATL_TOMCAT_PROXY_INTERNAL_IPS': '192.168.1.1',
        'CONFLUENCE_VERSION': '7.12.0',
    }

    container = run_image(docker_cli, image, environment=environment)
    _jvm = wait_for_proc(container, get_bootstrap_proc(container))

    xml = parse_xml(container, f'{get_app_install_dir(container)}/conf/server.xml')
    value = xml.find('.//Context/Valve[@className="org.apache.catalina.valves.RemoteIpValve"]')
    assert value.get('internalProxies') == environment.get('ATL_TOMCAT_PROXY_INTERNAL_IPS')

def test_seraph_defaults(docker_cli, image):
    container = run_image(docker_cli, image)
    _jvm = wait_for_proc(container, get_bootstrap_proc(container))

    xml = parse_xml(container, f'{get_app_install_dir(container)}/confluence/WEB-INF/classes/seraph-config.xml')
    param = xml.findall('.//param-name[.="autologin.cookie.age"]') == []


def test_seraph_login_set(docker_cli, image):
    container = run_image(docker_cli, image, environment={"ATL_AUTOLOGIN_COOKIE_AGE": "TEST_VAL"})
    _jvm = wait_for_proc(container, get_bootstrap_proc(container))

    xml = parse_xml(container, f'{get_app_install_dir(container)}/confluence/WEB-INF/classes/seraph-config.xml')
    assert xml.findall('.//param-value[.="TEST_VAL"]')[0].text == "TEST_VAL"


def test_conf_init_set(docker_cli, image):
    container = run_image(docker_cli, image, environment={"CONFLUENCE_HOME": "/tmp/"})
    _jvm = wait_for_proc(container, get_bootstrap_proc(container))

    init = container.file(f'{get_app_install_dir(container)}/confluence/WEB-INF/classes/confluence-init.properties')
    assert init.contains("confluence.home = /tmp/")


def test_confluence_xml_default_c3p0(docker_cli, image):
    container = run_image(docker_cli, image)
    _jvm = wait_for_proc(container, get_bootstrap_proc(container))

    xml = parse_xml(container, f'{get_app_home(container)}/confluence.cfg.xml')
    assert xml.findall('.//buildNumber')[0].text == "0"
    assert xml.findall('.//property[@name="hibernate.connection.url"]') == []
    assert xml.findall('.//property[@name="confluence.cluster.home"]') == []
    assert xml.findall('.//property[@name="lucene.index.dir"]')[0].text == '${confluenceHome}/index'


def test_confluence_lucene_index(docker_cli, image):
    container = run_image(docker_cli, image, environment={'ATL_LUCENE_INDEX_DIR': '/some/other/dir'})
    _jvm = wait_for_proc(container, get_bootstrap_proc(container))

    xml = parse_xml(container, f'{get_app_home(container)}/confluence.cfg.xml')
    assert xml.findall('.//property[@name="lucene.index.dir"]')[0].text == '/some/other/dir'

def test_confluence_xml_postgres(docker_cli, image, run_user):
    environment = {
        'ATL_DB_TYPE': 'postgresql',
        'ATL_JDBC_URL': 'atl_jdbc_url',
        'ATL_JDBC_USER': 'atl_jdbc_user',
        'ATL_JDBC_PASSWORD': 'atl_jdbc_password',
    }
    container = run_image(docker_cli, image, user=run_user, environment=environment)
    _jvm = wait_for_proc(container, get_bootstrap_proc(container))

    xml = parse_xml(container, f'{get_app_home(container)}/confluence.cfg.xml')
    assert xml.findall('.//property[@name="hibernate.connection.url"]')[0].text == "atl_jdbc_url"
    assert xml.findall('.//property[@name="hibernate.connection.username"]')[0].text == "atl_jdbc_user"
    assert xml.findall('.//property[@name="hibernate.connection.password"]')[0].text == "atl_jdbc_password"
    assert xml.findall('.//property[@name="confluence.database.choice"]')[0].text == "postgresql"
    assert xml.findall('.//property[@name="hibernate.dialect"]')[0].text == "com.atlassian.confluence.impl.hibernate.dialect.PostgreSQLDialect"
    assert xml.findall('.//property[@name="hibernate.connection.driver_class"]')[0].text == "org.postgresql.Driver"

    assert xml.findall('.//property[@name="hibernate.hikari.idleTimeout"]')[0].text == "30000"
    assert xml.findall('.//property[@name="hibernate.hikari.maximumPoolSize"]')[0].text == "100"
    assert xml.findall('.//property[@name="hibernate.hikari.minimumIdle"]')[0].text == "20"
    assert xml.findall('.//property[@name="hibernate.hikari.registerMbeans"]')[0].text == "true"


def test_confluence_xml_postgres_all_set(docker_cli, image, run_user):
    environment = {
        'ATL_DB_TYPE': 'postgresql',
        'ATL_JDBC_URL': 'atl_jdbc_url',
        'ATL_JDBC_USER': 'atl_jdbc_user',
        'ATL_JDBC_PASSWORD': 'atl_jdbc_password',
        'ATL_DB_POOLMAXSIZE': 'x100',
        'ATL_DB_POOLMINSIZE': 'x20',
        'ATL_DB_TIMEOUT': '40',
    }
    container = run_image(docker_cli, image, user=run_user, environment=environment)
    _jvm = wait_for_proc(container, get_bootstrap_proc(container))

    xml = parse_xml(container, f'{get_app_home(container)}/confluence.cfg.xml')
    assert xml.findall('.//property[@name="hibernate.connection.driver_class"]')[0].text == "org.postgresql.Driver"
    assert xml.findall('.//property[@name="hibernate.dialect"]')[0].text == "com.atlassian.confluence.impl.hibernate.dialect.PostgreSQLDialect"
    assert xml.findall('.//property[@name="hibernate.hikari.idleTimeout"]')[0].text == "40000"
    assert xml.findall('.//property[@name="hibernate.hikari.maximumPoolSize"]')[0].text == "x100"
    assert xml.findall('.//property[@name="hibernate.hikari.minimumIdle"]')[0].text == "x20"



def test_confluence_xml_postgres_c3p0(docker_cli, image, run_user):
    environment = {
        'CONFLUENCE_VERSION': '7.10.0',
        'ATL_DB_TYPE': 'postgresql',
        'ATL_JDBC_URL': 'atl_jdbc_url',
        'ATL_JDBC_USER': 'atl_jdbc_user',
        'ATL_JDBC_PASSWORD': 'atl_jdbc_password',
    }
    container = run_image(docker_cli, image, user=run_user, environment=environment)
    _jvm = wait_for_proc(container, get_bootstrap_proc(container))

    xml = parse_xml(container, f'{get_app_home(container)}/confluence.cfg.xml')
    assert xml.findall('.//property[@name="hibernate.connection.url"]')[0].text == "atl_jdbc_url"
    assert xml.findall('.//property[@name="hibernate.connection.username"]')[0].text == "atl_jdbc_user"
    assert xml.findall('.//property[@name="hibernate.connection.password"]')[0].text == "atl_jdbc_password"
    assert xml.findall('.//property[@name="confluence.database.choice"]')[0].text == "postgresql"
    assert xml.findall('.//property[@name="hibernate.dialect"]')[0].text == "com.atlassian.confluence.impl.hibernate.dialect.PostgreSQLDialect"
    assert xml.findall('.//property[@name="hibernate.connection.driver_class"]')[0].text == "org.postgresql.Driver"

    assert xml.findall('.//property[@name="hibernate.c3p0.min_size"]')[0].text == "20"
    assert xml.findall('.//property[@name="hibernate.c3p0.max_size"]')[0].text == "100"
    assert xml.findall('.//property[@name="hibernate.c3p0.timeout"]')[0].text == "30"
    assert xml.findall('.//property[@name="hibernate.c3p0.idle_test_period"]')[0].text == "100"
    assert xml.findall('.//property[@name="hibernate.c3p0.max_statements"]')[0].text == "0"
    assert xml.findall('.//property[@name="hibernate.c3p0.validate"]')[0].text == "true"
    assert xml.findall('.//property[@name="hibernate.c3p0.acquire_increment"]')[0].text == "1"
    assert xml.findall('.//property[@name="hibernate.c3p0.preferredTestQuery"]')[0].text == "select 1"


def test_confluence_xml_postgres_all_set_c3p0(docker_cli, image, run_user):
    environment = {
        'CONFLUENCE_VERSION': '7.10.0',
        'ATL_DB_TYPE': 'postgresql',
        'ATL_JDBC_URL': 'atl_jdbc_url',
        'ATL_JDBC_USER': 'atl_jdbc_user',
        'ATL_JDBC_PASSWORD': 'atl_jdbc_password',
        'ATL_DB_POOLMAXSIZE': 'x100',
        'ATL_DB_POOLMINSIZE': 'x20',
        'ATL_DB_TIMEOUT': 'x30',
        'ATL_DB_IDLETESTPERIOD': 'x100',
        'ATL_DB_MAXSTATEMENTS': 'x0',
        'ATL_DB_VALIDATE': 'xfalse',
        'ATL_DB_ACQUIREINCREMENT': 'x1',
        'ATL_DB_VALIDATIONQUERY': 'xselect 1'
    }
    container = run_image(docker_cli, image, user=run_user, environment=environment)
    _jvm = wait_for_proc(container, get_bootstrap_proc(container))

    xml = parse_xml(container, f'{get_app_home(container)}/confluence.cfg.xml')
    assert xml.findall('.//property[@name="hibernate.connection.driver_class"]')[0].text == "org.postgresql.Driver"
    assert xml.findall('.//property[@name="hibernate.dialect"]')[0].text == "com.atlassian.confluence.impl.hibernate.dialect.PostgreSQLDialect"
    assert xml.findall('.//property[@name="hibernate.c3p0.min_size"]')[0].text == "x20"
    assert xml.findall('.//property[@name="hibernate.c3p0.max_size"]')[0].text == "x100"
    assert xml.findall('.//property[@name="hibernate.c3p0.timeout"]')[0].text == "x30"
    assert xml.findall('.//property[@name="hibernate.c3p0.idle_test_period"]')[0].text == "x100"
    assert xml.findall('.//property[@name="hibernate.c3p0.max_statements"]')[0].text == "x0"
    assert xml.findall('.//property[@name="hibernate.c3p0.validate"]')[0].text == "xfalse"
    assert xml.findall('.//property[@name="hibernate.c3p0.acquire_increment"]')[0].text == "x1"
    assert xml.findall('.//property[@name="hibernate.c3p0.preferredTestQuery"]')[0].text == "xselect 1"


def test_confluence_xml_cluster_aws(docker_cli, image, run_user):
    environment = {
        'ATL_CLUSTER_TYPE': 'aws',
        'ATL_HAZELCAST_NETWORK_AWS_IAM_ROLE': 'atl_hazelcast_network_aws_iam_role',
        'ATL_HAZELCAST_NETWORK_AWS_IAM_REGION': 'atl_hazelcast_network_aws_iam_region',
        'ATL_HAZELCAST_NETWORK_AWS_HOST_HEADER': 'atl_hazelcast_network_aws_host_header',
        'ATL_HAZELCAST_NETWORK_AWS_TAG_KEY': 'atl_hazelcast_network_aws_tag_key',
        'ATL_HAZELCAST_NETWORK_AWS_TAG_VALUE': 'atl_hazelcast_network_aws_tag_value',
        'ATL_CLUSTER_NAME': 'atl_cluster_name',
        'ATL_CLUSTER_TTL': 'atl_cluster_ttl'
    }
    container = run_image(docker_cli, image, user=run_user, environment=environment)
    _jvm = wait_for_proc(container, get_bootstrap_proc(container))

    xml = parse_xml(container, f'{get_app_home(container)}/confluence.cfg.xml')

    assert xml.findall('.//property[@name="confluence.cluster"]')[0].text == "true"
    assert xml.findall('.//property[@name="confluence.cluster.join.type"]')[0].text == "aws"

    assert xml.findall('.//property[@name="confluence.cluster.aws.iam.role"]')[0].text == "atl_hazelcast_network_aws_iam_role"
    assert xml.findall('.//property[@name="confluence.cluster.aws.region"]')[0].text == "atl_hazelcast_network_aws_iam_region"
    assert xml.findall('.//property[@name="confluence.cluster.aws.host.header"]')[0].text == "atl_hazelcast_network_aws_host_header"
    assert xml.findall('.//property[@name="confluence.cluster.aws.tag.key"]')[0].text == "atl_hazelcast_network_aws_tag_key"
    assert xml.findall('.//property[@name="confluence.cluster.aws.tag.value"]')[0].text == "atl_hazelcast_network_aws_tag_value"
    assert xml.findall('.//property[@name="confluence.cluster.name"]')[0].text == "atl_cluster_name"
    assert xml.findall('.//property[@name="confluence.cluster.ttl"]')[0].text == "atl_cluster_ttl"

def test_confluence_xml_context_path(docker_cli, image, run_user):
    environment = {
        'ATL_TOMCAT_CONTEXTPATH': 'myconf',
    }
    container = run_image(docker_cli, image, user=run_user, environment=environment)
    _jvm = wait_for_proc(container, get_bootstrap_proc(container))

    xml = parse_xml(container, f'{get_app_home(container)}/confluence.cfg.xml')

    assert xml.findall('.//property[@name="confluence.webapp.context.path"]')[0].text == "/myconf"

def test_confluence_xml_cluster_multicast(docker_cli, image, run_user):
    environment = {
        'ATL_CLUSTER_TYPE': 'multicast',
        'ATL_CLUSTER_NAME': 'atl_cluster_name',
        'ATL_CLUSTER_TTL': 'atl_cluster_ttl',
        'ATL_CLUSTER_ADDRESS': '99.99.99.99'
    }
    container = run_image(docker_cli, image, user=run_user, environment=environment)
    _jvm = wait_for_proc(container, get_bootstrap_proc(container))

    xml = parse_xml(container, f'{get_app_home(container)}/confluence.cfg.xml')

    assert xml.findall('.//property[@name="confluence.cluster"]')[0].text == "true"
    assert xml.findall('.//property[@name="confluence.cluster.join.type"]')[0].text == "multicast"
    assert xml.findall('.//property[@name="confluence.cluster.name"]')[0].text == "atl_cluster_name"
    assert xml.findall('.//property[@name="confluence.cluster.ttl"]')[0].text == "atl_cluster_ttl"
    assert xml.findall('.//property[@name="confluence.cluster.address"]')[0].text == "99.99.99.99"


def test_confluence_xml_cluster_tcp(docker_cli, image, run_user):
    environment = {
        'ATL_CLUSTER_TYPE': 'tcp_ip',
        'ATL_CLUSTER_PEERS': '1.1.1.1,99.99.99.99',
        'ATL_CLUSTER_NAME': 'atl_cluster_name',
    }
    container = run_image(docker_cli, image, user=run_user, environment=environment)
    _jvm = wait_for_proc(container, get_bootstrap_proc(container))

    xml = parse_xml(container, f'{get_app_home(container)}/confluence.cfg.xml')

    assert xml.findall('.//property[@name="confluence.cluster"]')[0].text == "true"
    assert xml.findall('.//property[@name="confluence.cluster.join.type"]')[0].text == "tcp_ip"
    assert xml.findall('.//property[@name="confluence.cluster.name"]')[0].text == "atl_cluster_name"
    assert xml.findall('.//property[@name="confluence.cluster.peers"]')[0].text == "1.1.1.1,99.99.99.99"

def test_confluence_xml_license(docker_cli, image, run_user):
    environment = {
        'ATL_LICENSE_KEY': 'mylicense',
    }
    container = run_image(docker_cli, image, user=run_user, environment=environment)
    _jvm = wait_for_proc(container, get_bootstrap_proc(container))

    xml = parse_xml(container, f'{get_app_home(container)}/confluence.cfg.xml')

    assert xml.findall('.//property[@name="atlassian.license.message"]')[0].text == "mylicense"

def test_java_in_run_user_path(docker_cli, image):
    RUN_USER = 'confluence'
    container = run_image(docker_cli, image)
    proc = container.run(f'su -c "which java" {RUN_USER}')
    assert len(proc.stdout) > 0


def test_non_root_user(docker_cli, image):
    RUN_UID = 2002
    RUN_GID = 2002
    container = run_image(docker_cli, image, user=f'{RUN_UID}:{RUN_GID}')
    _jvm = wait_for_proc(container, get_bootstrap_proc(container))


def test_jvm_fallback_fonts(docker_cli, image):
    container = run_image(docker_cli, image)
    _jvm = wait_for_proc(container, get_bootstrap_proc(container))

    font = container.file("/opt/java/openjdk/lib/fonts/fallback/NotoSansGujarati-Regular.ttf")
    assert font.exists
    assert font.is_symlink


def test_confluence_xml_snapshot_properties(docker_cli, image, run_user):
    environment = {
        'ATL_SETUP_STEP': 'complete',
        'ATL_SETUP_TYPE': 'clustersetup',
        'ATL_BUILD_NUMBER': '8703',
        'ATL_SNAPSHOT_USED': 'true',
    }
    container = run_image(docker_cli, image, user=run_user, environment=environment)
    _jvm = wait_for_proc(container, get_bootstrap_proc(container))

    xml = parse_xml(container, f'{get_app_home(container)}/confluence.cfg.xml')

    assert xml.findall('.//setupStep')[0].text == "complete"
    assert xml.findall('.//setupType')[0].text == "clustersetup"
    assert xml.findall('.//buildNumber')[0].text == "8703"
    assert xml.findall('.//property[@name="hibernate.setup"]')[0].text == "true"


def test_confluence_xml_no_overwrite(docker_cli, image, run_user):
    environment = {
        'ATL_TOMCAT_CONTEXTPATH': 'myconf',
    }

    container = docker_cli.containers.run(image, detach=True, user=run_user, environment=environment)
    tihost = testinfra.get_host("docker://"+container.id)
    cfg = f'{get_app_home(tihost)}/confluence.cfg.xml'

    _jvm = wait_for_proc(tihost, get_bootstrap_proc(tihost))

    xml = parse_xml(tihost, cfg)
    assert xml.findall('.//property[@name="confluence.webapp.context.path"]')[0].text == "/myconf"

    container.exec_run(f"sed -i 's/myconf/otherval/' {cfg}")

    xml = parse_xml(tihost, cfg)
    assert xml.findall('.//property[@name="confluence.webapp.context.path"]')[0].text == "/otherval"

    container.restart(timeout=60)

    xml = parse_xml(tihost, cfg)
    assert xml.findall('.//property[@name="confluence.webapp.context.path"]')[0].text == "/otherval"


def test_confluence_xml_force_overwrite(docker_cli, image, run_user):
    environment = {
        'ATL_TOMCAT_CONTEXTPATH': 'myconf',
        'ATL_FORCE_CFG_UPDATE': 'y',
    }

    container = docker_cli.containers.run(image, detach=True, user=run_user, environment=environment)
    tihost = testinfra.get_host("docker://"+container.id)
    cfg = f'{get_app_home(tihost)}/confluence.cfg.xml'

    _jvm = wait_for_proc(tihost, get_bootstrap_proc(tihost))

    xml = parse_xml(tihost, cfg)
    assert xml.findall('.//property[@name="confluence.webapp.context.path"]')[0].text == "/myconf"

    container.exec_run(f"sed -i 's/myconf/otherval/' {cfg}")

    xml = parse_xml(tihost, cfg)
    assert xml.findall('.//property[@name="confluence.webapp.context.path"]')[0].text == "/otherval"

    container.stop(timeout=60)
    container.start()
    _jvm = wait_for_proc(tihost, get_bootstrap_proc(tihost))

    xml = parse_xml(tihost, cfg)
    assert xml.findall('.//property[@name="confluence.webapp.context.path"]')[0].text == "/myconf"


expected_db_properties = {
    'hikari': {
        'hibernate.hikari.idleTimeout': '30000',
        'hibernate.hikari.registerMbeans': 'true',
        'hibernate.hikari.maximumPoolSize': '100',
        'hibernate.hikari.minimumIdle': '20',
    },
    'c3p0': {
        'hibernate.c3p0.min_size': '20',
        'hibernate.c3p0.max_size': '100',
        'hibernate.c3p0.timeout': '30',
    }
}

@pytest.mark.parametrize("version,db_property", [('7.13.7', 'c3p0'), ('7.17.7', 'hikari'), ('6.9.0', 'c3p0'), ('8.0.0', 'hikari')])
def test_confluence_db_pool_property(docker_cli, image, version, db_property):
    environment = {
        'CONFLUENCE_VERSION': version,
        'ATL_JDBC_URL': 'postgresql:hostname',
        'ATL_DB_TYPE': 'postgresql'
    }
    container = run_image(docker_cli, image, environment=environment)

    xml = parse_xml(container, f'{get_app_home(container)}/confluence.cfg.xml')

    expected = expected_db_properties[db_property]

    for property, expected_value in expected.items():
        assert xml.findall(f'.//property[@name="{property}"]')[0].text == expected_value


def test_unset_secure_vars(docker_cli, image, run_user):
    environment = {
        'MY_TOKEN': 'tokenvalue',
    }
    container = docker_cli.containers.run(image, detach=True, user=run_user, environment=environment,
                                          ports={PORT: PORT})
    wait_for_state(STATUS_URL, expected_state='FIRST_RUN')
    var_unset_log_line = 'Unsetting environment var MY_TOKEN'
    wait_for_log(container, var_unset_log_line)


def test_skip_unset_secure_vars(docker_cli, image, run_user):
    environment = {
        'MY_TOKEN': 'tokenvalue',
        'ATL_UNSET_SENSITIVE_ENV_VARS': 'false',
    }
    container = docker_cli.containers.run(image, detach=True, user=run_user, environment=environment,
                                          ports={PORT: PORT})
    wait_for_state(STATUS_URL, expected_state='FIRST_RUN')
    var_unset_log_line = 'Unsetting environment var MY_TOKEN'
    rpat = re.compile(var_unset_log_line)
    logs = container.logs(stream=True, follow=True)
    li = TimeoutIterator(logs, timeout=1)
    for line in li:
        if line == li.get_sentinel():
            return
        line = line.decode('UTF-8')
        if rpat.search(line):
            raise EOFError(f"Found unexpected log line '{var_unset_log_line}'")
