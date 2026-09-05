#!/usr/bin/env python3
"""Opt-in live JV API test. Creates two small jobs; may consume service quota.

This checks login, multipart upload, polling, conversation continuation and logout.
It does not prove model tool-calling quality or generated-file production.
"""
import json
from pathlib import Path
import sys
import uuid
ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT/'lib'))
from jvcli import cli
from jvcli.safety import JvError,private_dir


def main():
    client=None
    try:
        base,user=cli._resolve_account()
    except JvError as exc:
        print(str(exc),file=sys.stderr)
        return 1
    print(f'Live JV API: {base}\nUsername: {user}\nThis test creates two small jobs and uploads a harmless generated text file.')
    if input('Type RUN to continue: ').strip()!='RUN':
        print('No requests made.');return 0
    folder=private_dir(cli.STATE_DIR/'live-checks'/uuid.uuid4().hex)
    fixture=folder/'sample.txt';fixture.write_text('This is a harmless JV API integration-test attachment.\n')
    try:
        client,_=cli._login_client(user,base)
        first=client.submit_job('Read the attachment and acknowledge it in one sentence.',file_paths=[fixture])
        completed=client.wait_for_job(first['id'],conversation_id=first['conversation_id'])
        if completed['status']!='succeeded' or not completed.get('answer'):
            raise JvError('First job did not return a successful text answer')
        second=client.submit_job('Reply with a short acknowledgement of this follow-up.',conversation_id=completed['conversation_id'])
        follow=client.wait_for_job(second['id'],conversation_id=completed['conversation_id'])
        if follow['status']!='succeeded' or not follow.get('answer'):
            raise JvError('Conversation follow-up failed')
        print(json.dumps({'ok':True,'first_job':first['id'],'follow_up_job':second['id'],
                          'conversation_id':completed['conversation_id'],
                          'generated_file_download_tested':False,'model_tool_quality_tested':False},indent=2))
        return 0
    except (JvError,KeyboardInterrupt) as exc:
        print('Live test failed or interrupted: '+str(exc),file=sys.stderr);return 1
    finally:
        if client:cli._logout(client)

if __name__=='__main__':
    raise SystemExit(main())
