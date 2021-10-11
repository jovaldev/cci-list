#!/usr/bin/env/ python3
""" Script for importing and extracting the CCI List from the DoD Cyber Exchange

Authors: Max Ullman <max.ullman@arcticwolf.com>

TODO:
-

"""

import datetime
import os
import re
import shutil
import sys
import tempfile
import urllib.request
import xml.etree.ElementTree as etree
import zipfile

# Webpage linking to latest zip
CCI_HOME = 'https://public.cyber.mil/stigs/cci/'

# Directory name to save CCI item md files under
CCI_SUBDIR = 'cci'

# CCI List XML Namespace
NS = 'http://iase.disa.mil/cci'


def get_tag(local_name, ns=NS):
    return '{{{}}}{}'.format(NS, local_name)


class CciItem:
    def __init__(self, elem):
        # This ptr is used to keep track of what child elements have been parsed and which should be parsed next
        # mainly with the hope that if down the line the schema changes and a new child or attribute gets 
        # introduced the script will notice and error out.
        self.ptr = 0
        self.elem = elem
        if self.elem.tag != get_tag('cci_item'):
            raise ValueError('Unexpected cci_item tag: {}'.format(self.elem.tag))
        if len(self.elem.attrib) != 1:
            raise ValueError('Unexpected cci_item attributes: {}'.format(self.elem.attrib))
        self.id = self.elem.attrib['id']
        self.status = self.parse_element('status')
        self.publish_date = self.parse_element('publishdate')
        self.contributor = self.parse_element('contributor')
        self.definition = self.parse_element('definition')
        self.types = self.parse_element_list('type')
        
        self.parameter = self.parse_element('parameter', required=False)
        self.notes = self.parse_element('note', required=False)
        
        self.references = self.parse_references()
        
        if self.ptr != len(self.elem):
            print(self.elem[self.ptr-1].tag)
            print(self.elem[self.ptr].tag)
            print(self.elem.attrib)
            raise ValueError('Unrecognized child in {}: {}'.format(self.id, self.elem[self.ptr].tag))
    
    
    def parse_element(self, tag, required=True):
        """ Returns text of next child if it's tag is tag or None. """
        if not tag.startswith('{'):
            tag = '{{{}}}{}'.format(NS, tag)
        child = self.elem[self.ptr]
        
        if child.tag == tag:
            if len(child.attrib):
                raise ValueError('Unexpected attributes found for {}: {}'.format(tag, self.elem.attrib))
            self.ptr += 1
            return child.text
        if required:
            raise ValueError('Missing required tag: {}'.format(tag))
        return None
    
    
    def parse_element_list(self, tag, required=True):
        """ Returns list of .text's from next children with tag """
        out = []
        while True:
            t = self.parse_element(tag, required=False)
            if t is not None:
                out.append(t)
            else:
                break
        if required and not len(out):
            raise ValueError('Missing required tag: {}'.format(tag))
        return out
    
    
    def parse_references(self):
        """ Returns list of references as (creator, title, version, location, index) """
        references = self.elem[self.ptr]
        if references.tag != '{{{}}}{}'.format(NS, 'references'):
            raise ValueError('Unexpected references tag: {}'.format(references.tag))
        out = []
        for r in references:
            if r.tag != '{{{}}}{}'.format(NS, 'reference'):
                raise ValueError('Unexpected reference tag: {}'.format(r.tag))
            if len(r.attrib) != 5:
                raise ValueError('Unexpected reference attributes: {}'.format(r.attrib))
            out.append((r.attrib['creator'], r.attrib['title'], r.attrib['version'], r.attrib['location'], r.attrib['index']))
        self.ptr += 1
        return out
    
    
    @staticmethod
    def source_markdown_helper(publish_date, version, import_date):
        return '''published to the [DoD Cyber Exchange]
(https://public.cyber.mil/stigs/cci/) (formerly the Information Assurance Support Environment
(IASE)) on {publish_date} as version {version} by the [Cyber Directorate of the Defense 
Information Systems Agency (DISA)](https://public.cyber.mil/about-cyber/) and was imported to 
this site on {import_date} for the convenience of Joval users and the broader security automation community.'''.format(publish_date=publish_date, version=version, import_date=import_date)
    
    
    def to_markdown(self, publish_date, version, import_date):
        """ Return markdown for this CCI Item """
        if self.notes:
            notes = '## Notes ##\n\n{}\n'.format(self.notes)
        else:
            notes = ''
        additional_info = [
            ('Published', to_date_str(datetime.date.fromisoformat(self.publish_date))),
            ('Contributed By', self.contributor),
            ('Status', self.status)
        ]
        if self.types:
            additional_info.append(('Types', ', '.join(self.types)))
        if self.parameter:
            additional_info.append(('Parameter', self.parameter))
        
        '\n'.join(['* [{title} § {index}, version {version}, created by {creator}]({location})'.format(title=title, index=index, version=version, creator=creator, location=location) for creator, title, version, location, index in self.references])
        
        return '''# {id}

{definition}

## References ##

{references}

{notes}
## Additional Information ##

{additional_info}

## Sources ##

This CCI was included in the CCI List {sources}

[View All](../README.md)
'''.format(
        id=self.id,
        definition=self.definition,
        references='\n'.join(['* [{title} § {index}, version {version}, created by {creator}]({location})'.format(title=title, index=index, version=version, creator=creator, location=location) for creator, title, version, location, index in self.references]),
        notes=notes,
        additional_info='\n'.join(['* **{}:** {}'.format(k, v) for k, v in additional_info]),
        sources=CciItem.source_markdown_helper(publish_date, version, import_date)
    )


def get_zip_url():
    """ Returns zip_url scraped """
    with urllib.request.urlopen(CCI_HOME) as res:
        s = res.read().decode(res.headers.get_content_charset())
    ms = re.findall(r'<tr class="file">.*?CCI List.*?href="(.*?)".*?</tr>', s, re.DOTALL)
    if len(ms) != 1:
        raise ValueError('Unable to scrape zip url')
    return ms[0]


def to_date_str(date):
    """ Returns date object as string like October 21st, 2021 """
    s = date.strftime('%B %d, %Y').replace(' 0', ' ')
    n = date.strftime('%d')
    if n in ['01', '21', '31']:
        suffix = 'st'
    elif n in ['02', '22']:
        suffix = 'nd'
    elif n in ['03', '23']:
        suffix = 'rd'
    else:
        suffix = 'th'
    return date.strftime('%B %d, %Y').replace(' 0', ' ').replace(',', suffix + ',')


def readme_markdown(cci_items, publish_date, version, import_date):
    """ Return markdown for main readme table of contents """
    rows = []
    for item in cci_items:
        link = '[{}]({}/{}.md)'.format(item.id, CCI_SUBDIR, item.id.lower())
        # right pad with whitespace until it's 31 chars
        rows.append(f'{link:<31} | {item.definition}')
    
    return '''# Control Correlation Identifiers

Control Correlation Identifiers (CCIs) provide a standard identifier and description for each of
the singular, actionable statements that comprise an IA control or IA best practice.

## CCI List ##

The following CCI list was {sources}

CCI                             | Definition
------------------------------- | -------------------------------
{rows}
'''.format(
        sources=CciItem.source_markdown_helper(publish_date, version, import_date),
        rows = '\n'.join(rows)
    )


def main(zip_path=None, output_root=None):
    if not output_root:
        output_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # clean up old cci directory
    cci_dir = os.path.join(output_root, CCI_SUBDIR)
    if os.path.exists(cci_dir):
        shutil.rmtree(cci_dir)
    os.mkdir(cci_dir)
    
    with tempfile.TemporaryDirectory() as tmpdirname:
        if not zip_path:
            zip_url = get_zip_url()
            base_name = zip_url[zip_url.rfind('/')+1:]
            zip_path = os.path.join(tmpdirname, base_name)
        
            urllib.request.urlretrieve(zip_url, zip_path)
        
        extracted_path = os.path.join(tmpdirname, os.path.basename(zip_path)[:-4])
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extracted_path)
        
        xml_paths = [p for p in os.listdir(extracted_path) if p.endswith('.xml')]
        if len(xml_paths) != 1:
            raise ValueError('CCI xml file not found')
        cci_list_path = os.path.join(extracted_path, xml_paths[0])
        
        tree = etree.parse(cci_list_path, parser=None)
        root = tree.getroot()
        
        metadata = root.find(get_tag('metadata'))
        publish_s = metadata.find(get_tag('publishdate')).text
        publish_dt = datetime.date.fromisoformat(publish_s)
        publish_date = to_date_str(publish_dt)
        version = metadata.find(get_tag('version')).text
        import_date = to_date_str(datetime.datetime.today())
        
        cci_items = []
        for child in root.find(get_tag('cci_items')):
            item = CciItem(child)
            with open(os.path.join(cci_dir, '{}.md'.format(item.id.lower())), 'w') as f:
                f.write(item.to_markdown(publish_date, version, import_date))
            cci_items.append(item)
        
        if not len(cci_items):
            raise ValueError('No cci items found')
        
        with open(os.path.join(output_root, 'README.md'), 'w') as f:
            f.write(readme_markdown(cci_items, publish_date, version, import_date))

if __name__ == '__main__':
    if '-h' in sys.argv or len(sys.argv) > 2:
        print('Usage: python3 importer.py [optional u_cci_list.zip path]')
        sys.exit()
    zip_path = sys.argv[1] if len(sys.argv) == 2 else None
    main(zip_path=zip_path)
