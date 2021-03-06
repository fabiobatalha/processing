# coding: utf-8
import os
import thriftpy
import json
import logging

from thriftpy.rpc import make_client
from xylose.scielodocument import Article, Journal

LIMIT = 1000

logger = logging.getLogger(__name__)

ratchet_thrift = thriftpy.load(
    os.path.join(os.path.dirname(__file__))+'/ratchet.thrift')

articlemeta_thrift = thriftpy.load(
    os.path.join(os.path.dirname(__file__))+'/articlemeta.thrift')

citedby_thrift = thriftpy.load(
    os.path.join(os.path.dirname(__file__))+'/citedby.thrift')

accessstats_thrift = thriftpy.load(
    os.path.join(os.path.dirname(__file__))+'/access_stats.thrift')

publication_stats_thrift = thriftpy.load(
    os.path.join(os.path.dirname(__file__))+'/publication_stats.thrift')

class ServerError(Exception):
    def __init__(self, message=None):
        self.message = message or 'thirftclient: ServerError'
    
    def __str__(self):
        return repr(self.message)


class AccessStats(object):

    def __init__(self, address, port):
        """
        Cliente thrift para o Access Stats.
        """
        self._address = address
        self._port = port

    @property
    def client(self):

        client = make_client(
            accessstats_thrift.AccessStats,
            self._address,
            self._port
        )
        return client

    def _compute_access_lifetime(self, query_result):

        data = []

        for publication_year in query_result['aggregations']['publication_year']['buckets']:
            for access_year in publication_year['access_year']['buckets']:
                 data.append([
                    publication_year['key'],
                    access_year['key'],
                    int(access_year['access_html']['value']),
                    int(access_year['access_abstract']['value']),
                    int(access_year['access_pdf']['value']),
                    int(access_year['access_epdf']['value']),
                    int(access_year['access_total']['value'])
                ])

        return sorted(data)

    def access_lifetime(self, issn, collection, raw=False):

        body = {
            "query": {
                "bool": {
                    "must": [{
                            "match": {
                                "collection": collection
                            }
                        },
                        {
                            "match": {
                                "issn": issn
                            }
                        }
                    ]
                }
            },
            "size": 0,
            "aggs": {
                "publication_year": {
                    "terms": {
                        "field": "publication_year",
                        "size": 0,
                        "order": {
                            "access_total": "desc"
                        }
                  },
                  "aggs": {
                        "access_total": {
                            "sum": {
                                "field": "access_total"
                            }
                        },
                        "access_year": {
                            "terms": {
                                "field": "access_year",
                                "size": 0,
                                "order": {
                                    "access_total": "desc"
                                }
                            },
                            "aggs": {
                                "access_total": {
                                    "sum": {
                                        "field": "access_total"
                                    }
                                },
                                "access_abstract": {
                                    "sum": {
                                        "field": "access_abstract"
                                    }
                                },
                                "access_epdf": {
                                    "sum": {
                                        "field": "access_epdf"
                                    }
                                },
                                "access_html": {
                                    "sum": {
                                        "field": "access_html"
                                    }
                                },
                                "access_pdf": {
                                    "sum": {
                                        "field": "access_pdf"
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        query_parameters = [
            accessstats_thrift.kwargs('size', '0')
        ]

        query_result = json.loads(self.client.search(json.dumps(body), query_parameters))

        computed = self._compute_access_lifetime(query_result)

        return query_result if raw else computed


class PublicationStats(object):

    def __init__(self, address, port):
        """
        Cliente thrift para o PublicationStats.
        """
        self._address = address
        self._port = port

    @property
    def client(self):
        client = make_client(
            publication_stats_thrift.PublicationStats,
            self._address,
            self._port
        )

        return client

    def _compute_first_included_document_by_journal(self, query_result):

        if len(query_result.get('hits', {'hits': []}).get('hits', [])) == 0:
            return None

        return query_result['hits']['hits'][0].get('_source', None)

    def first_included_document_by_journal(self, issn, collection):

        body = {
            "query": {
                "filtered": {
                    "query": {
                        "bool": {
                            "must": [
                                {
                                    "match": {
                                        "collection": collection
                                    }
                                },
                                {
                                    "match": {
                                        "issn": issn
                                    }
                                }
                            ]
                        }
                    }
                }
            },
            "sort": [
                {
                    "publication_date": {
                        "order": "asc"
                    }
                }
            ]
        }

        query_parameters = [
            publication_stats_thrift.kwargs('size', '1')
        ]

        query_result = json.loads(self.client.search('article', json.dumps(body), query_parameters))

        return self._compute_first_included_document_by_journal(query_result)


    def _compute_last_included_document_by_journal(self, query_result):

        if len(query_result.get('hits', {'hits': []}).get('hits', [])) == 0:
            return None

        return query_result['hits']['hits'][0].get('_source', None)

    def last_included_document_by_journal(self, issn, collection, metaonly=False):

        body = {
            "query": {
                "filtered": {
                    "query": {
                        "bool": {
                            "must": [
                                {
                                    "match": {
                                        "collection": collection
                                    }
                                },
                                {
                                    "match": {
                                        "issn": issn
                                    }
                                }
                            ]
                        }
                    },
                    "filter": {
                        "exists": {
                            "field": "publication_date"
                        }
                    }
                }
            },
            "sort": [
                {
                    "publication_date": {
                        "order": "desc"
                    }
                }
            ]
        }

        query_parameters = [
            publication_stats_thrift.kwargs('size', '1')
        ]

        query_result = json.loads(self.client.search('article', json.dumps(body), query_parameters))

        return self._compute_last_included_document_by_journal(query_result)

class Citedby(object):

    def __init__(self, address, port):
        """
        Cliente thrift para o Citedby.
        """
        self._address = address
        self._port = port

    @property
    def client(self):
        client = make_client(
            citedby_thrift.Citedby,
            self._address,
            self._port
        )

        return client

    def citedby_pid(self, code, metaonly=False):

        data = self.client.citedby_pid(code, metaonly)

        return data

class Ratchet(object):

    def __init__(self, address, port):
        """
        Cliente thrift para o Ratchet.
        """
        self._address = address
        self._port = port

    @property
    def client(self):
        client = make_client(
            ratchet_thrift.RatchetStats,
            self._address,
            self._port
        )

        return client

    def document(self, code):

        data = self.client.general(code=code)

        return data

class ArticleMeta(object):

    def __init__(self, address, port):
        """
        Cliente thrift para o Articlemeta.
        """
        self._address = address
        self._port = port

    @property
    def client(self):

        client = make_client(
            articlemeta_thrift.ArticleMeta,
            self._address,
            self._port
        )
        return client


    def journals(self, collection=None, issn=None):
        offset = 0
        while True:
            identifiers = self.client.get_journal_identifiers(collection=collection, issn=issn, limit=LIMIT, offset=offset)
            if len(identifiers) == 0:
                raise StopIteration

            for identifier in identifiers:

                journal = self.client.get_journal(
                    code=identifier.code[0], collection=identifier.collection)

                jjournal = json.loads(journal)

                xjournal = Journal(jjournal)

                logger.info('Journal loaded: %s_%s' % ( identifier.collection, identifier.code))

                yield xjournal

            offset += 1000

    def exists_article(self, code, collection):
        try:
            return self.client.exists_article(
                code,
                collection
            )
        except:
            msg = 'Error checking if document exists: %s_%s' % (collection, code)
            raise ServerError(msg)

    def set_doaj_id(self, code, collection, doaj_id):
        try:
            article = self.client.set_doaj_id(
                code,
                collection,
                doaj_id
            )
        except:
            msg = 'Error senting doaj id for document: %s_%s' % (collection, code)
            raise ServerError(msg)


    def document(self, code, collection, replace_journal_metadata=True, fmt='xylose'):
        try:
            article = self.client.get_article(
                code=code,
                collection=collection,
                replace_journal_metadata=True, 
                fmt=fmt
            )
        except:
            msg = 'Error retrieving document: %s_%s' % (collection, code)
            raise ServerError(msg)

        jarticle = None
        try:
            jarticle = json.loads(article)
        except:
            msg = 'Fail to load JSON when retrienving document: %s_%s' % (collection, code)
            raise ServerError(msg)

        if not jarticle:
            logger.warning('Document not found for : %s_%s' % ( collection, code))
            return None

        if fmt == 'xylose':
            xarticle = Article(jarticle)
            logger.info('Document loaded: %s_%s' % ( collection, code))
            return xarticle
        else:
            logger.info('Document loaded: %s_%s' % ( collection, code))
            return article


    def documents(self, collection=None, issn=None, from_date=None,
        until_date=None, fmt='xylose'):
        offset = 0
        while True:
            identifiers = self.client.get_article_identifiers(
                collection=collection, issn=issn, from_date=from_date,
                until_date=until_date, limit=LIMIT, offset=offset)

            if len(identifiers) == 0:
                raise StopIteration

            for identifier in identifiers:

                document = self.document(
                    code=identifier.code,
                    collection=identifier.collection,
                    replace_journal_metadata=True, 
                    fmt=fmt
                )

                yield document

            offset += 1000

    def collections(self):
        
        return [i for i in self._client.get_collection_identifiers()]