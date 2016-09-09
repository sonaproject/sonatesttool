import ast
import commands
import os
import socket
import time

import keystoneclient.v2_0.client as kclient
import pexpect

from api.config import ReadConfig
from api.instance import InstanceTester
from api.network import NetworkTester
from api.onos_info import ONOSInfo
from api.reporter2 import Reporter

PROMPT = ['~# ', 'onos> ', '\$ ', '\# ', ':~$ ', '$ ']
CMD_PROMPT = '\[SONA\]\# '


class SonaTest:

    def __init__(self, config_file):
        self.conf = ReadConfig(config_file)
        self.onos_info = self.conf.get_onos_info()
        self.inst_conf = self.conf.get_instance_config()
        self.auth = self.conf.get_auth_conf()
        self.conn_timeout = self.conf.get_ssh_conn_timeout()
        self.ping_timeout = self.conf.get_floating_ip_check_timeout()
        self.result_skip_mode = self.conf.get_state_check_result_skip_mode()
        self.wget_url = self.conf.get_wget_url()
        self.instance = InstanceTester(self.conf)
        self.network = NetworkTester(self.conf)
        self.onos = ONOSInfo(self.conf)
        self.reporter = Reporter(self.conf)

    def ssh_connect(self, host, user, port, password):
        try:
            ssh_newkey = 'want to continue connecting'
            if '' is port:
                connStr = 'ssh ' + user + '@' + host
            else:
                connStr = 'ssh '+ '-p ' + port + ' ' + user + '@' + host
            Reporter.REPORT_MSG('   >> connection : %s', connStr)
            conn = pexpect.spawn(connStr)
            ret = conn.expect([pexpect.TIMEOUT, ssh_newkey, '[P|p]assword:'], timeout=self.conn_timeout)
            if ret == 0:
                Reporter.REPORT_MSG('   >> [%s] Error Connection to SSH Servcer(%d)', host, ret)
                self.ssh_disconnect(conn)
                return False
            if ret == 1:
                # Reporter.REPORT_MSG('   >> [%s] wait %s ', host, ssh_newkey)
                conn.sendline('yes')
                ret = conn.expect([pexpect.TIMEOUT, '[P|p]assword'], timeout=self.conn_timeout)

            conn.sendline(password)
            conn.expect(PROMPT, timeout=self.conn_timeout)

        except Exception, e:
            Reporter.REPORT_MSG('   >> [%s] Error Connection to SSH Servcer (timeout except)', host)
            self.ssh_disconnect(conn)
            return False

        return conn

    def ssh_disconnect(self, ssh_conn):
        if ssh_conn.isalive():
            ssh_conn.close()

    def ssh_send_command(self, ssh_conn, cmd):
        ssh_conn.sendline(cmd)
        ssh_conn.expect(PROMPT)
        return ssh_conn.before

    def ssh_conn_send_command(self, conn_info, cmd):
        ssh_conn = self.ssh_connect(conn_info['host'], conn_info['user'], conn_info['port'], conn_info['password'])
        if ssh_conn is False:
            return False

        ssh_conn.sendline(cmd)
        ssh_conn.expect(PROMPT, timeout=3)
        ssh_conn.close()
        return ssh_conn.before

    # def ssh_ping(self, inst1, inst2, dest):
    def ssh_ping(self, inst1, *insts):
        if len(insts) > 1:
            Reporter.unit_test_start(False, inst1, insts[0], insts[1])
        else:
            Reporter.unit_test_start(False, inst1, insts[0])

        if len(insts) > 2 or len(insts) < 1:
            Reporter.REPORT_MSG('   >> Check the arguments(Min : 2, Max : 3)')
            Reporter.unit_test_stop('nok', False)
            return False
        try:
            # floating ip
            floating_ip = self.instance.get_instance_floatingip(inst1)
            if None is floating_ip:
                Reporter.REPORT_MSG('   >> Get floating_ip[%s] fail', floating_ip)
                Reporter.unit_test_stop('nok', False)
                return False

            # check dest type
            ping_ip = insts[-1]
            try:
                socket.inet_aton(insts[-1])
            except socket.error:
                ping_ip = self.instance.get_instance_ip(insts[-1])
                if None is ping_ip:
                    Reporter.unit_test_stop('nok', False)
                    return False
                pass

            # clear ssh key
            clear_key = 'ssh-keygen -f "' + os.path.expanduser('~')+'/.ssh/known_hosts" -R ' + floating_ip
            commands.getstatusoutput(clear_key)

            # first ssh connection
            # get first instance connection info
            inst_info_1 = ast.literal_eval(self.inst_conf[inst1])
            conn = self.ssh_connect(floating_ip, inst_info_1['user'], '', inst_info_1['password'])
            if conn is False:
                Reporter.unit_test_stop('nok', False)
                return False

            # get second instance connection info
            if len(insts) > 1:
            # if ':' in inst2:
                name_list = insts[0].split(':')
                inst_info_2 = ast.literal_eval(self.inst_conf[name_list[0]])
                inst2_ip = self.instance.get_instance_ip(insts[0])
                ssh_cmd = 'ssh ' + inst_info_2['user'] + '@' + inst2_ip
                conn.sendline(ssh_cmd)
                # Reporter.REPORT_MSG('   >> connection: %s', ssh_cmd)
                ssh_newkey = 'want to continue connecting'
                ret = conn.expect([pexpect.TIMEOUT, ssh_newkey, '[P|p]assword:'], timeout=self.conn_timeout)
                if ret == 0:
                    Reporter.REPORT_MSG('   >> [%s] Error Connection to SSH Server(%d)', inst2_ip, ret)
                    Reporter.unit_test_stop('nok', False)
                    self.ssh_disconnect(conn)
                    return False
                if ret == 1:
                    conn.sendline('yes')
                    ret = conn.expect([pexpect.TIMEOUT, '[P|p]assword'], timeout=self.conn_timeout)
                if ret == 2:
                    ret = conn.expect([pexpect.TIMEOUT, '[P|p]assword'], timeout=self.conn_timeout)

                conn.sendline(inst_info_2['password'])
                conn.expect(PROMPT, timeout=self.conn_timeout)

            cmd = 'ping ' + ping_ip + ' -w 2'
            conn.sendline(cmd)
            conn.expect(PROMPT, timeout=self.conn_timeout)

            # parsing loss rate
            ping_list = conn.before.splitlines()
            self.ssh_disconnect(conn)
            ping_result = False
            for list in ping_list:
                if 'loss' in list:
                    split_list = list.split(', ')
                    for x in split_list:
                        if '%' in x:
                            result = x.split('%')
                            if 0 is int(result[0]):
                                ping_result = True
                            break

            # result output
            if True is ping_result:
                if len(insts) > 1:
                    Reporter.REPORT_MSG('   >> result : %s --> %s --> %s : ok',
                                        inst1, insts[0], insts[-1])
                else:
                    Reporter.REPORT_MSG('   >> result : %s --> %s : ok',
                                        inst1, insts[-1])
                Reporter.unit_test_stop('ok', False)
            else:
                if len(insts) > 1:
                    Reporter.REPORT_MSG('   >> result : %s --> %s --> %s : nok',
                                        inst1, insts[0], insts[-1])
                else:
                    Reporter.REPORT_MSG('   >> result : %s --> %s : nok',
                                        inst1, insts[-1])

                Reporter.REPORT_MSG("%s", '\n'.join('     >> '
                                                    + line for line in ping_list))

                Reporter.unit_test_stop('nok', False)
                return False

            return True
        except:
            Reporter.exception_err_write()
            return False

    def change_prompt(self, conn):
        change_cmd = "set prompt='[SONA]\# '"
        for i in range(2):
            try:
                # print change_cmd
                conn.sendline(change_cmd)
                conn.expect(CMD_PROMPT, timeout=1)
                # print '===== set comp'
                break
            except Exception, e:
                change_cmd = "PS1='[SONA]\# '"
                pass

    def openstack_get_token(self, report_flag=None):
        if report_flag is None:
            Reporter.unit_test_start(True)
        try:
            keystone = kclient.Client(auth_url=self.auth['auth_url'],
                                      username=self.auth['username'],
                                      password=self.auth['api_key'],
                                      tenant_name=self.auth['project_id'])
            token = keystone.auth_token
            if not token:
                Reporter.REPORT_MSG("   >> OpentStack Authentication NOK --->")
                if report_flag is None:
                    Reporter.unit_test_stop('nok')
                    return False
            Reporter.REPORT_MSG("   >> OpenStack Authentication OK ---> token: %s", token)

            if report_flag is None:
                Reporter.unit_test_stop('ok')
            return True
        except:
            if report_flag is None:
                Reporter.exception_err_write()
            return False

    def openstack_get_service(self, report_flag=None):
        if report_flag is None:
            Reporter.unit_test_start(True)
        try:
            keystone = kclient.Client(auth_url=self.auth['auth_url'],
                                      username=self.auth['username'],
                                      password=self.auth['api_key'],
                                      tenant_name=self.auth['project_id'])
            service_list = [{a.name: a.enabled} for a in keystone.services.list()]

            for i in range(len(service_list)):
                if service_list[i].values()[0] is False:
                    Reporter.REPORT_MSG("   >> OpenStack Service status NOK ---> %s", service_list[i])
                    if report_flag is None:
                        Reporter.unit_test_stop('nok')
                    return False

            Reporter.REPORT_MSG("   >> OpenStack Service status OK ---> %s", service_list)

            if report_flag is None:
                Reporter.unit_test_stop('ok')

            return True

        except:
            if report_flag is None:
                Reporter.exception_err_write()
            return False

    def floating_ip_check(self, inst1):
        Reporter.unit_test_start(False)
        try:
            # floating ip
            floating_ip = self.instance.get_instance_floatingip(inst1)
            if None is floating_ip:
                Reporter.REPORT_MSG('   >> Get floating_ip[%s] fail', floating_ip)
                Reporter.unit_test_stop('nok', False)
                return False
            ping_result = []
            sucs_cnt = 0
            (exitstatus, outtext) = commands.getstatusoutput('uname -a')
            if 'Linux' in outtext:
                cmd = 'ping ' + floating_ip + ' -w 1'
            else:
                cmd = 'ping -t 1 ' + floating_ip

            for i in range(self.ping_timeout):
                (exitstatus, outtext) = commands.getstatusoutput(cmd)
                ping_result.append(outtext)
                if 'from ' + floating_ip in outtext:
                    sucs_cnt += 1
                    if 2 is sucs_cnt:
                        break

            if 2 is sucs_cnt:
                Reporter.REPORT_MSG('   >> result : local --> %s : ok', floating_ip)
                time.sleep(5)
                Reporter.unit_test_stop('ok', False)
                return True
            else:
                Reporter.REPORT_MSG('   >> result : local --> %s : nok', floating_ip)
                Reporter.unit_test_stop('nok', False)
            return False
        except:
            Reporter.exception_err_write()

    def onos_and_openstack_check(self):
        Reporter.unit_test_start(True)
        try:
            flag = 'no'

            app_stat = self.onos.application_status(report_flag=flag)
            device_stat = self.onos.devices_status(report_flag=flag)
            token_stat = self.openstack_get_token(report_flag=flag)
            service_stat = self.openstack_get_service(report_flag=flag)

            if (app_stat and device_stat and token_stat and service_stat):
                Reporter.unit_test_stop('ok')
            else:
                Reporter.unit_test_stop('nok')
                if False is self.result_skip_mode:
                    Reporter.test_summary()
                    os._exit(1)
        except:
            Reporter.exception_err_write()


    # def ssh_ping(self, inst1, inst2, dest):
    def ssh_wget(self, *insts):
        if len(insts) in [1, 2]:
            Reporter.unit_test_start(False, *insts)
        else:
            Reporter.unit_test_start(False, *insts)
            Reporter.REPORT_MSG('   >> Check the arguments(need 1 or 2)')
            Reporter.unit_test_stop('nok', False)
            return False

        cmd = 'wget ' + self.wget_url
        wget_lines = self.second_ssh_cmd(cmd, *insts)
        if wget_lines[0] is False:
            Reporter.unit_test_stop('nok', False)
        elif wget_lines[0] is 'timeout':
            self.wget_clear(*insts)
            wget_progress = None
            for line in wget_lines[1]:
                if '%' in line:
                    wget_progress = line

            if wget_progress is not None:
                Reporter.REPORT_MSG('   >> wet download very slow : \n   >>     "%s"', wget_progress)
                Reporter.unit_test_stop('skip', False)
            return

        wget_percent = ''
        wget_progress = ''
        for line in wget_lines:
            if 'error' in line.lower():
                Reporter.REPORT_MSG('   >> wget request fail: "%s"', line)
                Reporter.unit_test_stop('nok', False)
            elif '%' in line:
                wget_percent = line.split('%')[0].split(' ')[-1]
                wget_progress = line

        if int(wget_percent) in range(5, 101):
            Reporter.REPORT_MSG('   >> wet download Succ : \n   >>     "%s"', wget_progress)
        else:
            Reporter.REPORT_MSG('   >> wet download under 5 percent : \n   >>     %s', wget_progress)

        self.wget_clear(*insts)

        Reporter.unit_test_stop('ok')
        return

    def wget_clear(self, *insts):
        cmd = 'killall -9 wget'
        self.second_ssh_cmd(cmd, *insts)

        cmd = 'rm ' + self.wget_url.split('/')[-1] + '*' + ' ' + 'wget-log*'
        self.second_ssh_cmd(cmd, *insts)
        return


    def second_ssh_cmd(self, cmd, *insts):
        # floating ip
        # floating_ip = self.instance.get_instance_floatingip(insts[0])
        floating_ip = "10.10.2.76"
        if None is floating_ip:
            Reporter.REPORT_MSG('   >> Get floating_ip[%s] fail', floating_ip)
            Reporter.unit_test_stop('nok', False)
            return [False]

        # conn = self.ssh_connect(floating_ip, inst_info_1['user'], '', inst_info_1['password'])
        conn = self.ssh_connect(floating_ip, 'root', '', 'root')
        if conn is False:
            Reporter.REPORT_MSG('   >>  %s ssh connection fail.', insts[0])
            Reporter.unit_test_stop('nok', False)
            return [False]

        # get second instance connection info
        if len(insts) is 2:
            # if ':' in inst2:
            name_list = insts[1].split(':')
            inst_info_2 = ast.literal_eval(self.inst_conf[name_list[0]])
            # inst2_ip = self.instance.get_instance_ip(insts[1])
            # ssh_cmd = 'ssh ' + inst_info_2['user'] + '@' + inst2_ip
            ssh_cmd = 'ssh root@10.10.2.77'
            conn.sendline(ssh_cmd)
            # Reporter.REPORT_MSG('   >> connection: %s', ssh_cmd)

            ssh_newkey = 'want to continue connecting'
            ret = conn.expect([pexpect.TIMEOUT, ssh_newkey, '[P|p]assword:'], timeout=self.conn_timeout)
            if ret == 0:
                # Reporter.REPORT_MSG('   >> [%s] Error Connection to SSH Server(%d)', inst2_ip, ret)
                Reporter.REPORT_MSG('   >> [%s] Error Connection to SSH Server(%d)', '10.10.2.77', ret)
                Reporter.unit_test_stop('nok', False)
                self.ssh_disconnect(conn)
                return [False]

            if ret == 1:
                conn.sendline('yes')
                ret = conn.expect([pexpect.TIMEOUT, '[P|p]assword'], timeout=self.conn_timeout)
            if ret == 2:
                ret = conn.expect([pexpect.TIMEOUT, '[P|p]assword'], timeout=self.conn_timeout)

            # conn.sendline(inst_info_2['password'])
            conn.sendline('root')
            conn.expect(PROMPT, timeout=self.conn_timeout)

        try:
            conn.sendline(cmd)
            conn.expect(PROMPT, timeout=self.conn_timeout)
        except pexpect.TIMEOUT:
            Reporter.REPORT_MSG('   >> wget download Timeout. limit %s', self.conn_timeout)
            self.ssh_disconnect(conn)
            return ['timeout', conn.before.splitlines()]

        self.ssh_disconnect(conn)
        return conn.before.splitlines()

