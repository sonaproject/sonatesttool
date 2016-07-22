import requests
import json
from api.reporter2 import Reporter

class ONOSInfo():
    _config=''

    def __init__(self, config):
        # print 'init'
        ONOSCtrl._config = config

    def onos_create_session(self, conn_info):
        conn = requests.session()
        conn.auth = (conn_info['user'], conn_info['password'])
        return conn

    def app_info(self, conn_info, app_name):
        conn = self.onos_create_session(conn_info)
        url = 'http://' + conn_info['host'] + ':8181/onos/v1/applications/' + app_name
        header = {'Accept': 'application/json'}
        # print json.dumps(conn.get(url, headers=header).json(),indent=4, separators=('',':'))
        return dict(conn.get(url, headers=header).json())['state'].encode('utf-8')

    def device_info(self, conn_info):
        conn = self.onos_create_session(conn_info)
        url = 'http://' + conn_info['host'] + ':8181/onos/v1/devices/'
        header = {'Accept': 'application/json'}
        ret = json.dumps(conn.get(url, headers=header).json(), ensure_ascii=False, sort_keys=False).encode('utf-8')
        dev_list = json.loads(ret)
        return dev_list['devices']

    def port_info(self, conn_info, dev_id):
        conn = self.onos_create_session(conn_info)
        url = 'http://' + conn_info['host'] + ':8181/onos/v1/devices/' + dev_id + '/ports'
        header = {'Accept': 'application/json'}
        # print json.dumps(conn.get(url, headers=header).json(),indent=4, separators=('',':'))
        ret = json.dumps(conn.get(url, headers=header).json(), ensure_ascii=False, sort_keys=False).encode('utf-8')
        port_list = json.loads(ret)

        result = []
        for x in dict(port_list)['ports']:
            port_name = dict(dict(x)['annotations'])
            port_status = dict(x)
            # test
            # if 'vxlan' in port_name['portName']:
            #     port_status['isEnabled'] = False
            result.append({port_name['portName'] : port_status['isEnabled']})

        return result

    def device_status(self, conn_info):
        try:
            dev_list = self.device_info(conn_info)
            br_int_status = 0
            vxlan_status = 0
            dev_cnt = 0
            for i in range(len(dev_list)):
                dev_info_dic = dict(dev_list[i])
                if 'OF_13' not in dict(dev_info_dic['annotations'])['protocol']:
                    continue
                dev_cnt += 1
                if False is dev_info_dic['available']:
                    Reporter.REPORT_MSG('   >> [%s] device[%s] status nok', conn_info['host'], dev_info_dic['id'])
                    return False

                # Port status(br-int)
                port_result = self.port_info(conn_info, dev_info_dic['id'])
                status = 0
                for x in port_result:
                    str = dict(x)
                    if str.has_key('br-int') == True :
                        status = 1
                        break
                br_int_status += status

                # Port status(vxlan)
                for x in port_result:
                    str = dict(x)
                    if str.has_key('vxlan') == True:
                        if True is str['vxlan']:
                            vxlan_status += 1

            # br-int
            if dev_cnt != br_int_status:
                Reporter.REPORT_MSG('   >> [%s] port status(br-int) -- nok', conn_info['host'])
                return False

            # vxlan-int
            if dev_cnt != vxlan_status:
                Reporter.REPORT_MSG('   >> [%s] port status(vxlan)  -- nok', conn_info['host'])
                return False

            Reporter.REPORT_MSG('   >> [%s] device, port status -- ok', conn_info['host'])
            return True
        except:
            Reporter.exception_err_write()

    def onos_application_status(self):
        Reporter.unit_test_start()
        try:
            onos_info = self._config.get_onos_info()
            state_list=[]
            conn_info = {}
            state_info = {}
            for onos_ip in onos_info.onos_list:
                conn_info['host'] = onos_ip
                conn_info['user'] = onos_info.user_id
                conn_info['password'] = onos_info.password

                ret = self.app_info(conn_info, 'org.onosproject.openstackswitching')
                state_info['openstackswitching'] = ret; state_list.append(ret)
                ret = self.app_info(conn_info, 'org.onosproject.openstackrouting')
                state_info['openstackrouting'] = ret; state_list.append(ret)
                ret = self.app_info(conn_info, 'org.onosproject.openstacknetworking')
                state_info['openstacknetworking'] = ret; state_list.append(ret)
                ret = self.app_info(conn_info, 'org.onosproject.openstacknode')
                state_info['openstacknode'] = ret; state_list.append(ret)
                ret = self.app_info(conn_info, 'org.onosproject.openstackinterface')
                state_info['openstackinterface'] = ret; state_list.append(ret)

                if 'INSTALLED' in state_list:
                    Reporter.REPORT_MSG('   >> [%s][NOK] : %s', onos_ip, state_info)
                    Reporter.unit_test_stop('nok')
                    return False
                Reporter.REPORT_MSG('   >> [%s][OK] : %s', onos_ip, state_info)
            Reporter.unit_test_stop('ok')
            return True
        except:
            Reporter.exception_err_write()

    def onos_devices_status(self):
        Reporter.unit_test_start()
        try:
            onos_info = self._config.get_onos_info()
            conn_info = {}
            for onos_ip in onos_info.onos_list:
                conn_info['host'] = onos_ip
                conn_info['user'] = onos_info.user_id
                conn_info['port'] = onos_info.ssh_port
                conn_info['password'] = onos_info.password
                ret = self.device_status(conn_info)
                if False is ret:
                    Reporter.unit_test_stop('nok')
                    return

            Reporter.unit_test_stop('ok')
        except:
            Reporter.exception_err_write()