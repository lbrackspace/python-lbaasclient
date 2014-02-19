from lbaasclient.v1_1 import certs
from lbaasclient.tests import utils
from lbaasclient.tests.v1_1 import fakes


cs = fakes.FakeClient()


class FlavorsTest(utils.TestCase):

    def test_create_cert(self):
        cert = cs.certs.create()
        cs.assert_called('POST', '/os-certificates')
        self.assertTrue(isinstance(cert, certs.Certificate))

    def test_get_root_cert(self):
        cert = cs.certs.get()
        cs.assert_called('GET', '/os-certificates/root')
        self.assertTrue(isinstance(cert, certs.Certificate))
