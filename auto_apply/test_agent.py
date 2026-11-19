import unittest
from agent import match, key
class AgentTests(unittest.TestCase):
    def setUp(self):
        self.p={"locations":["india"],"skills":["aws","jenkins","docker"],"max_required_years":3}
        self.j={"company":"Example","title":"DevOps Engineer","location":"India","description":"2-4 years AWS Jenkins Docker"}
    def test_match(self):
        self.assertEqual(match(self.j,self.p)[0],100)
    def test_senior(self):
        self.assertEqual(match(dict(self.j,title="Senior DevOps Engineer"),self.p)[0],0)
    def test_experience(self):
        self.assertEqual(match(dict(self.j,description="5+ years AWS Jenkins Docker"),self.p)[0],0)
    def test_unknown_experience(self):
        self.assertEqual(match(dict(self.j,description="AWS Jenkins Docker"),self.p)[3],"experience unclear")
    def test_duplicate(self):
        self.assertEqual(key(self.j),key(dict(self.j,url="other")))
if __name__=="__main__": unittest.main()
