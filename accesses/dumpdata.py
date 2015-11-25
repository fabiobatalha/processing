# coding: utf-8
"""
Esse processamento condença os metadados de documentos com os dados de acessos.
"""
import sys
import argparse
import logging
import re
import json
import codecs
import datetime

import choices

import utils

__version__ = 0.1

logger = logging.getLogger(__name__)

SUPPLBEG_REGEX = re.compile(r'^0 ')
SUPPLEND_REGEX = re.compile(r' 0$')
REGEX_PDF_PATH = re.compile(r'/pdf.*\.pdf$')
FROM = '1500-01-01'
UNTIL = datetime.datetime.now().isoformat()[0:10]
DAYLY_GRANULARITY = False
OUTPUT_FORMAT = 'csv'


def _config_logging(logging_level='INFO', logging_file=None):

    allowed_levels = {
        'DEBUG': logging.DEBUG,
        'INFO': logging.INFO,
        'WARNING': logging.WARNING,
        'ERROR': logging.ERROR,
        'CRITICAL': logging.CRITICAL
    }

    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    logger.setLevel(allowed_levels.get(logging_level, 'INFO'))

    if logging_file:
        hl = logging.FileHandler(logging_file, mode='a')
    else:
        hl = logging.StreamHandler()

    hl.setFormatter(formatter)
    hl.setLevel(allowed_levels.get(logging_level, 'INFO'))

    logger.addHandler(hl)

    return logger


def pdf_keys(fulltexts):

    keys = []

    if not 'pdf' in fulltexts:
        return keys

    for language, url in fulltexts['pdf'].items():
        path = REGEX_PDF_PATH.search(url)
        if path:
            keys.append(path.group().upper())

    return keys


def fbpe_key(code):
    """
    input:
        'S0102-67202009000300001'
    output:
        'S0102-6720(09)000300001'
    """

    begin = code[0:10]
    year = code[12:14]
    end = code[14:]

    return '%s(%s)%s' % (begin, year, end)


def eligible_match_keys(document):
    keys = []

    keys.append(document.publisher_id)
    keys.append(fbpe_key(document.publisher_id))
    if document.doi:
        keys.append(document.doi)
    keys += pdf_keys(document.fulltexts())

    return keys


def country(country):
    if country in choices.ISO_3166:
        return country
    if country in choices.ISO_3166_COUNTRY_AS_KEY:
        return choices.ISO_3166_COUNTRY_AS_KEY[country]
    return 'undefined'

def get_date_timestamp(date):
    try:
        return datetime.datetime.strptime(date, '%Y-%m').isoformat()
    except ValueError:
        try:
            return datetime.datetime.strptime(date, '%Y-%m-%d').isoformat()
        except ValueError:
            return date

    return date

def issuelabel(document):
    label_volume = document.volume if document.volume else ''
    label_issue = document.issue if document.issue else ''

    label_suppl_issue = ' suppl %s' % document.supplement_issue if document.supplement_issue else ''

    if label_suppl_issue:
        label_issue += label_suppl_issue

    label_suppl_volume = ' suppl %s' % document.supplement_volume if document.supplement_volume else ''

    if label_suppl_volume:
        label_issue += label_suppl_volume
    
    label_issue = SUPPLBEG_REGEX.sub('', label_issue)
    label_issue = SUPPLEND_REGEX.sub('', label_issue)

    label_volume = 'n.' + label_volume
    label_issue = 'v.' + label_issue

    itens = [
        document.journal.abbreviated_title,
        ' '.join([label_volume, label_issue]),
        document.publication_date[0:4]
        ]

    return ', '.join(itens)

def join_metadata_with_accesses(document, accesses_date, accesses):

    data = {}
    data['id'] = '_'.join([document.collection_acronym, document.publisher_id])
    data['pid'] = document.publisher_id
    data['issn'] = document.journal.scielo_issn
    data['journal_title'] = document.journal.title
    data['issue'] = document.publisher_id[0:18]
    data['document_title'] = ''
    if document.original_title():
        data['document_title'] = document.original_title()
    elif document.translated_titles():
        for language, title in document.translated_titles().items():
            if title:
                data['document_title'] = title
                break


    data['issue_title'] = issuelabel(document)
    data['processing_date'] = document.processing_date
    data['publication_date'] = document.publication_date
    data['publication_year'] = document.publication_date[0:4]
    subject_areas = document.journal.subject_areas or ['undefined']
    data['subject_areas'] = [i for i in subject_areas]
    data['collection'] = document.collection_acronym
    data['document_type'] = document.document_type
    data['languages'] = list(set([i for i in document.languages()]+[document.original_language() or 'undefined']))
    data['aff_countries'] = ['undefined']
    if document.mixed_affiliations:
        data['aff_countries'] = list(set([country(aff.get('country', 'undefined')) for aff in document.mixed_affiliations]))
    data['access_date'] = get_date_timestamp(accesses_date)
    data['access_year'] = accesses_date[:4]
    data['access_month'] = accesses_date[5:7]
    data['access_day'] = accesses_date[8:]
    data['access_abstract'] = accesses.get('abstract', 0)
    data['access_html'] = accesses.get('html', 0)
    data['access_pdf'] = accesses.get('pdf', 0)
    data['access_epdf'] = accesses.get('readcube', 0)
    data['access_total'] = sum([v for i, v in accesses.items()])

    return data


def join_accesses(unique_id, accesses, from_date, until_date, dayly_granularity):
    """
    Esse metodo recebe 1 ou mais chaves para um documento em específico para que
    os acessos sejam recuperados no Ratchet e consolidados em um unico id.
    Esse processo é necessário pois os acessos de um documento podem ser registrados
    para os seguintes ID's (PID, PID FBPE, Path PDF).
    PID: Id original do SciELO ex: S0102-67202009000300001
    PID FBPE: Id antigo do SciELO ex: S0102-6720(09)000300001
    Path PDF: Quando o acesso é feito diretamente para o arquivo PDF no FS do
    servidor ex: /pdf/rsp/v12n10/v12n10.pdf
    """
    logger.debug('joining accesses for: %s' % unique_id)
    joined_data = {}
    listed_data = []
    def joining_monthly(joined_data, atype, data):

        if 'total' in data:
            del(data['total'])

        for year, months in data.items():
            del(months['total'])
            for month in months:

                dt = '%s-%s' % (year[1:], month[1:])
                if not dt >= from_date[:7] or not dt <= until_date[:7]:
                    continue
                joined_data.setdefault(dt, {})
                joined_data[dt].setdefault(atype, 0)
                joined_data[dt][atype] += data[year][month]['total']

        return joined_data

    def joining_dayly(joined_data, atype, data):

        if 'total' in data:
            del(data['total'])

        for year, months in data.items():
            del(months['total'])
            for month, days in months.items():
                del(days['total'])
                for day in days:
                    dt = '%s-%s-%s' % (year[1:], month[1:], day[1:])
                    if not dt >= from_date or not dt <= until_date:
                        continue
                    joined_data.setdefault(dt, {})
                    joined_data[dt].setdefault(atype, 0)
                    joined_data[dt][atype] += data[year][month][day]

        return joined_data

    joining = joining_monthly
    if dayly_granularity:
        joining = joining_dayly

    for data in accesses:
        for key, value in data.items():
            if not key in ['abstract', 'html', 'pdf', 'readcube']:
                continue
            joined_data = joining(joined_data, key, value)

    return joined_data


class Dumper(object):

    def __init__(self, collection, issns=None, from_date=FROM, until_date=UNTIL,
        dayly_granularity=DAYLY_GRANULARITY, fmt=OUTPUT_FORMAT, output_file=None):

        self._ratchet = utils.ratchet_server()
        self._articlemeta = utils.articlemeta_server()
        self.from_date = from_date
        self.until_date = until_date
        self.dayly_granularity = dayly_granularity
        self.output_file=output_file
        self.issns = issns
        self.collection = collection

        self.fmt = self.fmt_csv
        if fmt == 'json':
            self.fmt = self.fmt_json


    def get_accesses(self, issn):

        for document in self._articlemeta.documents(collection=self.collection, issn=issn):
            accesses = []
            keys = eligible_match_keys(document)
            logger.debug('keys to join for %s: %s' % (document.publisher_id, str(keys)))
            for key in keys:
                data = self._ratchet.document(key)
                jdata = json.loads(data)
                if 'objects' in jdata and len(jdata['objects']) > 0:
                    accesses.append(jdata['objects'][0])
            joined_accesses = join_accesses(document.publisher_id,
                accesses, self.from_date, self.until_date,
                self.dayly_granularity)

            for adate, adata in joined_accesses.items():
                yield join_metadata_with_accesses(document, adate, adata)

    def fmt_json(self, data):
        return json.dumps(data)

    def fmt_csv(self, data):

        line = [
            data['collection'],
            data['pid'],
            data['issn'],
            data['journal_title'],
            data['issue'],
            data['issue_title'],
            data['document_title'],
            data['processing_date'],
            data['publication_date'],
            data['publication_year'],
            data['document_type'],
            ', '.join(data['subject_areas']),
            ', '.join(data['languages']),
            ', '.join(data['aff_countries']),
            data['access_date'],
            data['access_date'][:4],
            data['access_date'][5:7],
            data['access_date'][8:],
            data.get('access_abstract', 0),
            data.get('access_html', 0),
            data.get('access_pdf', 0),
            data.get('access_epdf', 0),
            data['access_total']
        ]

        return ','.join(['"%s"' % i for i in line])

    def run(self):

        if not self.issns:
            self.issns = [None]

        if not self.output_file:
            for issn in self.issns:
                for data in self.get_accesses(issn=issn):
                    print(self.fmt(data))
            exit()

        with codecs.open(self.output_file, 'w', encoding='utf-8') as f:
            for issn in self.issns:
                for data in self.get_accesses(issn=issn):
                    f.write(u'%s\r\n' % self.fmt(data))


def main():
    parser = argparse.ArgumentParser(
        description='Dump accesses'
    )

    parser.add_argument(
        'issns',
        nargs='*',
        help='ISSN\'s separated by spaces'
    )

    parser.add_argument(
        '--collection',
        '-c',
        help='Collection Acronym'
    )

    parser.add_argument(
        '--dayly_granularity',
        '-d',
        action='store_true',
        help='Accesses granularity default will be monthly if not specified'
    )

    parser.add_argument(
        '--from_date',
        '-b',
        default=FROM,
        help='Delimite the accesses start period'
    )

    parser.add_argument(
        '--until_date',
        '-u',
        default=UNTIL,
        help='Delimite the accesses end period'
    )

    parser.add_argument(
        '--output_format',
        '-f',
        choices=['json', 'csv'],
        default=OUTPUT_FORMAT,
        help='Output format'
    )

    parser.add_argument(
        '--output_file',
        '-r',
        help='File to receive the dumped data'
    )

    parser.add_argument(
        '--logging_file',
        '-o',
        help='Full path to the log file'
    )

    parser.add_argument(
        '--logging_level',
        '-l',
        default='DEBUG',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        help='Logggin level'
    )

    args = parser.parse_args()
    _config_logging(args.logging_level, args.logging_file)
    logger.info('Dumping data for: %s' % args.collection)
 
    issns = None
    if len(args.issns) > 0:
        issns = utils.ckeck_given_issns(args.issns)

    if not utils.is_valid_date(args.from_date):
        logger.error('Invalid from date: %s' % args.from_date)
        exit()

    if not utils.is_valid_date(args.until_date):
        logger.error('Invalid until date: %s' % args.until_date)
        exit()

    dumper = Dumper(args.collection, issns, args.from_date, args.until_date,
        args.dayly_granularity, args.output_format, args.output_file)

    dumper.run()
