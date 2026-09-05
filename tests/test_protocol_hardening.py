import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from jvcli.protocol import (parse_agent_output, build_jv_prompt, flatten_tools, _truncate_utf8,
                           _json_candidate, sanitize_internal_text, validate_arguments)
from jvcli.safety import (JvError, ProtocolError, strict_json, positive_number,
                         atomic_write, read_private_json, terminal_text, redact_data)
from jvcli.transport import validate_base_url, JvClientConfig, _parse_retry_after


TOOLS = [{'type':'function','name':'shell_command','parameters':{'type':'object', 'required':['command'],
          'properties':{'command':{'type':'string'},'timeout_ms':{'type':'integer'}},'additionalProperties':False}}]
CATALOG = flatten_tools(TOOLS)[1]


class ProtocolHardening(unittest.TestCase):
    def call(self, obj, catalog=CATALOG):
        return parse_agent_output(json.dumps(obj), catalog)

    def test_empty_call_list_rejected_not_infinite_recursion(self):
        with self.assertRaises(ProtocolError): self.call({'type':'tool_calls','calls':[]})

    def test_nameless_call_rejected_not_infinite_recursion(self):
        with self.assertRaises(ProtocolError): self.call({'type':'tool_call','arguments':{}})

    def test_unknown_tool_rejected(self):
        with self.assertRaises(ProtocolError): self.call({'type':'tool_call','name':'delete_everything','arguments':{}})

    def test_duplicate_protocol_keys_rejected(self):
        with self.assertRaises(ProtocolError): parse_agent_output('{"type":"final","type":"tool_call","text":"x"}', CATALOG)

    def test_duplicate_argument_keys_rejected(self):
        with self.assertRaises(ProtocolError): parse_agent_output('{"type":"tool_call","name":"shell_command","arguments":{"command":"a","command":"b"}}', CATALOG)

    def test_normalization_collision_rejected(self):
        with self.assertRaises(ProtocolError): parse_agent_output(r'{"type":"tool_call","name":"shell_command","arguments":{"command":"a","timeout_ms":1,"timeout\_ms":2}}', CATALOG)

    def test_json_example_in_prose_is_not_executed(self):
        text='An example is {"type":"tool_call","name":"shell_command","arguments":{"command":"echo NO"}}.'
        with self.assertRaises(ProtocolError): parse_agent_output(text,CATALOG)

    def test_final_containing_tool_example_stays_text(self):
        text=json.dumps({'type':'tool_call','name':'shell_command','arguments':{'command':'pwd'}})
        self.assertEqual(self.call({'type':'final','text':text})[0]['type'],'message')

    def test_argument_string_requires_object(self):
        with self.assertRaises(ProtocolError): self.call({'type':'tool_call','name':'shell_command','arguments':'[]'})

    def test_argument_string_object_accepted(self):
        out=self.call({'type':'tool_call','name':'shell_command','arguments':'{"command":"pwd"}'})
        self.assertEqual(json.loads(out[0]['arguments']),{'command':'pwd'})

    def test_required_argument_checked(self):
        with self.assertRaises(ProtocolError): self.call({'type':'tool_call','name':'shell_command','arguments':{}})

    def test_wrong_argument_type_checked(self):
        with self.assertRaises(ProtocolError): self.call({'type':'tool_call','name':'shell_command','arguments':{'command':123}})

    def test_unknown_argument_checked(self):
        with self.assertRaises(ProtocolError): self.call({'type':'tool_call','name':'shell_command','arguments':{'command':'pwd','surprise':1}})

    def test_boolean_not_integer(self):
        with self.assertRaises(ProtocolError): self.call({'type':'tool_call','name':'shell_command','arguments':{'command':'pwd','timeout_ms':True}})

    def test_nan_rejected(self):
        with self.assertRaises(ProtocolError): parse_agent_output('{"type":"tool_call","name":"shell_command","arguments":{"command":"pwd","timeout_ms":NaN}}',CATALOG)

    def test_custom_type_mismatch_rejected(self):
        with self.assertRaises(ProtocolError): self.call({'type':'custom_tool_call','name':'shell_command','input':'pwd'})

    def test_custom_patch_preserved_exactly(self):
        raw='*** Begin Patch\n*** Add File: a.py\n+print("\\n")\n*** End Patch'
        result=self.call({'type':'custom_tool_call','name':'apply_patch','input':raw},{(None,'apply_patch'):'custom'})
        self.assertEqual(result[0]['input'],raw)

    def test_namespace_is_not_silently_discarded(self):
        with self.assertRaises(ProtocolError): self.call({'type':'tool_call','namespace':'attacker','name':'shell_command','arguments':{'command':'pwd'}})

    def test_valid_namespaced_tool(self):
        catalog={("files","read"):'function'}
        result=self.call({'type':'tool_call','namespace':'files','name':'read','arguments':{}},catalog)
        self.assertEqual(result[0]['namespace'],'files')

    def test_many_calls_limited(self):
        with self.assertRaises(ProtocolError): self.call({'type':'tool_calls','calls':[{}]*9})

    def test_multiple_calls_have_unique_ids(self):
        call={'name':'shell_command','arguments':{'command':'pwd'}}
        result=self.call({'type':'tool_calls','calls':[call,call]})
        self.assertEqual(len(set(item['call_id'] for item in result)),2)

    def test_nested_calls_rejected(self):
        with self.assertRaises(ProtocolError): self.call({'type':'tool_calls','calls':[{'type':'tool_calls','calls':[]}]})

    def test_empty_final_rejected(self):
        with self.assertRaises(ProtocolError): self.call({'type':'final','text':''})

    def test_plain_final_text_supported(self):
        self.assertEqual(parse_agent_output('All tests passed.',CATALOG)[0]['content'][0]['text'],'All tests passed.')

    def test_windows_paths_not_unicode_decoded(self):
        value=r'C:\new\test\file.py'
        result=self.call({'type':'final','text':value})
        self.assertEqual(result[0]['content'][0]['text'],value)

    def test_valid_json_command_backslashes_preserved(self):
        value=r'''printf '%s\n' '\*' 'C:\new' '''
        result=self.call({'type':'tool_call','name':'shell_command','arguments':{'command':value}})
        self.assertEqual(json.loads(result[0]['arguments'])['command'],value)

    def test_actual_json_newlines_render(self):
        self.assertEqual(self.call({'type':'final','text':'a\nb'})[0]['content'][0]['text'],'a\nb')

    def test_identity_only_rebrand(self):
        text='You are Codex. Read codex.rs and https://api.openai.com; user said ChatGPT.'
        result=sanitize_internal_text(text)
        self.assertIn('You are JV CLI.',result)
        self.assertIn('codex.rs',result)
        self.assertIn('api.openai.com',result)
        self.assertIn('ChatGPT',result)

    def test_string_input_handled(self):
        prompt,_=build_jv_prompt({'input':'Explain this project','tools':[]})
        self.assertIn('Explain this project',prompt)

    def test_omitted_message_type_handled(self):
        prompt,_=build_jv_prompt({'input':[{'role':'user','content':'hello'}]})
        self.assertIn('[user message]',prompt)

    def test_latest_user_kept_after_many_outputs(self):
        inputs=[{'role':'user','content':'IMPORTANT GOAL'}]+[{'type':'function_call_output','call_id':'c','output':'x'*18000}]*5
        prompt,_=build_jv_prompt({'input':inputs,'tools':TOOLS})
        self.assertIn('IMPORTANT GOAL',prompt)
        self.assertIn('Older items omitted',prompt)
        self.assertLessEqual(len(prompt.encode()),96*1024)

    def test_oversized_tool_schema_not_admitted(self):
        tool={'type':'function','name':'huge','parameters':{'description':'x'*40000}}
        prompt,catalog=build_jv_prompt({'tools':[tool],'input':'hi'})
        self.assertNotIn((None,'huge'),catalog)
        self.assertNotIn('"name":"huge"',prompt)

    def test_tools_none_not_admitted(self):
        _,catalog=build_jv_prompt({'tools':TOOLS,'tool_choice':'none','input':'hi'})
        self.assertFalse(catalog)

    def test_previous_response_id_explicitly_rejected(self):
        with self.assertRaises(ProtocolError): build_jv_prompt({'previous_response_id':'resp_old','input':[]})

    def test_image_not_silently_omitted(self):
        with self.assertRaises(ProtocolError): build_jv_prompt({'input':[{'role':'user','content':[{'type':'input_image','image_url':'x'}]}]})

    def test_hosted_tool_not_silently_promised(self):
        with self.assertRaises(ProtocolError): build_jv_prompt({'tools':[{'type':'web_search'}]})

    def test_utf8_truncation_stays_valid_and_bounded(self):
        for budget in (1,20,70,100):
            for tail in (True,False):
                value=_truncate_utf8('\u0e01\u0e32'*100,budget,tail)
                self.assertLessEqual(len(value.encode()),budget)


class LocalSafety(unittest.TestCase):
    def test_portable_atomic_private_state(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'state/config.json'
            atomic_write(p,'{"username":"user"}\n')
            self.assertEqual(p.stat().st_mode&0o777,0o600)
            self.assertEqual(p.parent.stat().st_mode&0o777,0o700)
            self.assertEqual(read_private_json(p)['username'],'user')

    def test_symlink_state_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            target=Path(td)/'original';target.write_text('keep')
            link=Path(td)/'config.json';link.symlink_to(target)
            with self.assertRaises(JvError): atomic_write(link,'changed')
            self.assertEqual(target.read_text(),'keep')

    def test_malformed_config_not_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'config.json';p.write_text('{')
            with self.assertRaises(JvError): read_private_json(p)
            self.assertEqual(p.read_text(),'{')

    def test_terminal_control_sequences_removed(self):
        self.assertEqual(terminal_text('\x1b[31mred\x1b[0m\x1b]52;c;secret\x07\x00'),'red')

    def test_escaped_secret_redacted_before_serialization(self):
        secret='a"b\\c'
        out=redact_data({'text':secret},(secret,))
        self.assertEqual(out['text'],'[REDACTED]')

    def test_numeric_limits_reject_bad_values(self):
        for value in ('nan','inf',0,-1,True,'bad'):
            with self.subTest(value=value):
                with self.assertRaises(JvError): positive_number(value,'test')

    def test_base_url_rejects_credentials_and_unsafe_origins(self):
        for url in ('http://example.com','https://u:p@example.com','https://example.com/path',
                    'https://example.com?token=x','https://example.com#x','https://example.com:bad',
                    'https://example.com:0','https://example.com:65536','https://exa mple.com','https://x\\y'):
            with self.subTest(url=url):
                with self.assertRaises(JvError): validate_base_url(url)

    def test_loopback_ipv6_and_normalized_url(self):
        self.assertEqual(validate_base_url('http://[::1]:456/'),'http://[::1]:456')
        self.assertEqual(validate_base_url('https://EXAMPLE.COM/'),'https://example.com')

    def test_invalid_retry_configuration_rejected(self):
        for value in (0,21,True,1.5):
            with self.assertRaises(JvError): JvClientConfig(max_poll_errors=value)

    def test_retry_after_seconds_and_date(self):
        self.assertEqual(_parse_retry_after('12'),12)
        self.assertEqual(_parse_retry_after('bad'),0)
        with patch('jvcli.transport.time.time',return_value=0):
            self.assertEqual(_parse_retry_after('Thu, 01 Jan 1970 00:00:10 GMT'),10)
