python3 - <<'PY'
import sys
sys.path.insert(0,'/home/ubuntu/multigauge')
import geometry_check as g
raw=g.command(['ign','service','-s','/world/multigauge_demo/generate_world_sdf','--reqtype','ignition.msgs.SdfGeneratorConfig','--reptype','ignition.msgs.StringMsg','--timeout','5000','--req','global_entity_gen_config { expand_include_tags { data: true } }'])
print('response_chars',len(raw),'lines',len(raw.splitlines()),'prefix_type',repr(raw[:8]),'data_fields',len(g.re.findall(r'^data:',raw,flags=g.re.MULTILINE)))
try:
 data=g.stringmsg_data(raw)
 print('xml_chars',len(data),'prefix_type',repr(data[:8]))
 try:
  root=g.ET.fromstring(data)
  print('parsed_root',root.tag)
 except Exception as e:
  print('xml_parse_error_type',type(e).__name__,'position',e.position,'code',getattr(e,'code',None)); bad=data.splitlines()[e.position[0]-1]; print('line_length',len(bad),'tag_tokens',g.re.findall(r'</?[A-Za-z0-9_-]+',bad),'bad_codepoint',ord(bad[e.position[1]]) if e.position[1]<len(bad) else None)
except Exception as e:
 print('string_parse_error_type',type(e).__name__)
PY