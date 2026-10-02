import yaml,datetime,copy
from pathlib import Path
from jinja2.nativetypes import NativeEnvironment
from types import SimpleNamespace
A=[a for a in yaml.safe_load((Path(__file__).parent / 'appliance-alarms.yaml').read_text()) if str(a['id']).startswith('safety_')]
class Simulator:
 def __init__(self,a):
  self.a=a;self.ts=1800000000.;self.s={};self.attrs={};self.messages=[];self.reports={};self.env=NativeEnvironment()
  self.env.globals.update(states=self.States(self),is_state=lambda e,s:self.s.get(e)==s,state_attr=lambda e,k:self.attrs.get(e,{}).get(k),is_number=self.number,now=lambda:datetime.datetime.fromtimestamp(self.ts,datetime.timezone.utc),as_timestamp=self.stamp)
  self.env.filters['float']=lambda v,d=0:float(v) if self.number(v) else d
 def number(self,v):
  try:float(v);return v is not None
  except (ValueError,TypeError):return False
 def stamp(self,x,default=None):
  if hasattr(x,'timestamp'):return x.timestamp()
  try:return float(x)
  except:return default
 class States:
  def __init__(self,p):self.p=p
  def __call__(self,e):return self.p.s.get(e,'unknown')
  def __getitem__(self,e):return SimpleNamespace(last_reported=datetime.datetime.fromtimestamp(self.p.reports.get(e,self.p.ts),datetime.timezone.utc))
 def render(self,x,v):
  if isinstance(x,str):return self.env.from_string(x).render(v)
  if isinstance(x,list):return [self.render(y,v) for y in x]
  if isinstance(x,dict):return {k:self.render(y,v) for k,y in x.items()}
  return x
 def conditions(self,cs,v):
  return all(self.render(c['value_template'],v) if c['condition']=='template' else self.s.get(c['entity_id'])==c['state'] for c in cs)
 def run(self,steps,v):
  for x in steps:
   if 'variables' in x:
    for k,z in x['variables'].items():v[k]=self.render(z,v)
   elif 'if' in x:self.run(x['then'] if self.conditions(x['if'],v) else x.get('else',[]),v.copy())
   elif 'action' in x:
    d=self.render(x.get('data',{}),v);e=x.get('target',{}).get('entity_id');act=x['action']
    if act=='input_datetime.set_datetime':self.attrs[e]={'timestamp':d['timestamp']}
    elif act.startswith('input_boolean.'):self.s[e]='on' if act.endswith('turn_on') else 'off'
    elif act.startswith('notify.') or act=='persistent_notification.create':self.messages.append((act,d.get('title')))
 def tick(self,dt=0):self.ts+=dt;self.run(self.a['actions'],{})
for a in A:
 q=Simulator(a);chest='chest' in a['id'];prefix='chest_freezer' if chest else 'kitchen_refrigerator';temp='sensor.chest_freezer_thermometer_temperature' if chest else 'sensor.freezer_thermometer_temperature';power='sensor.'+prefix+'_power';latch='input_boolean.'+prefix+'_temperature_alarm';hold=2700 if chest else 3600
 q.s.update({temp:'30',power:'70',latch:'off'});q.tick();q.tick(hold-1);assert q.s[latch]=='off'
 # A restart loses automation-local variables but preserves helper state; the simulator has no per-run memory.
 restored=Simulator(a);restored.ts=q.ts;restored.s=copy.deepcopy(q.s);restored.attrs=copy.deepcopy(q.attrs);q=restored;q.tick(1);assert q.s[latch]=='on';n=len(q.messages);q.tick(60);assert len(q.messages)==n
 q.tick(3540);assert len(q.messages)==n+2
 q.s[temp]='-5';q.tick();q.tick(599);assert q.s[latch]=='on';q.tick(1);assert q.s[latch]=='off'
 # Invalid readings cannot recover an active alarm or reset pending heat detection.
 q=Simulator(a);q.s.update({temp:'30',power:'70',latch:'off'});q.tick();q.tick(hold-100);q.s[temp]='unavailable';q.tick(20);q.s[temp]='30';q.tick(80);assert q.s[latch]=='on'
 # A genuine below-threshold observation resets the dwell period.
 q=Simulator(a);q.s.update({temp:'30',power:'70',latch:'off'});q.tick();q.tick(hold-10);q.s[temp]='-5';q.tick();q.s[temp]='30';q.tick(20);assert q.s[latch]=='off';q.tick(hold);assert q.s[latch]=='on'
 # Power loss, duplicate suppression, recovery, and recurrence.
 q=Simulator(a);q.s.update({temp:'5' if chest else '-5',power:'0',latch:'off'});q.tick();q.tick(1200 if chest else 1800);assert any('no power' in (t or '') for _,t in q.messages);n=len(q.messages);q.tick(60);assert len(q.messages)==n;q.s[power]='70';q.tick();q.s[power]='0';q.tick();q.tick(1200 if chest else 1800);assert len(q.messages)>n
 # Missing sensor and missing plug are detected after 30 minutes, even with a fresh last_reported.
 q=Simulator(a);q.s.update({temp:'unavailable',power:'unavailable',latch:'off'});q.tick();q.tick(1800);assert any('thermometer offline' in (t or '') for _,t in q.messages);assert any('plug silent' in (t or '') for _,t in q.messages)
 print(a['alias']+': restart, reset, hourly repeat, recovery, missing-data and power tests passed')
