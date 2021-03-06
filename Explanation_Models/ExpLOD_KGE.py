import heapq
import pickle
import math
import pandas as pd
import numpy as np
import random

from surprise import SVD, Reader, Dataset

from scipy.spatial.distance import cosine
from collections import defaultdict
from SPARQLWrapper import SPARQLWrapper2, SPARQLWrapper, JSON


class ExpLOD_KGE:
    """
    The proposed KG embedding based approach.
    The parameters:
        recommender: the algorithm used for generate recommandations. Values should be in ['cbf', 'svd', 'hybrid']
        nb_po: number of properties used for generated explanations
        nb_rec: number of top-N items recommended for user
        input_dict: user input representing rating dict {'iid': 'rating'}
    """
    def __init__(self, recommender='cbf', nb_po=3, nb_rec=1, input_dict=None, alpha=0.5, beta=0.5):
        self.recommender = recommender
        self.nb_po = nb_po
        self.nb_rec = nb_rec
        self.input_dict = input_dict
        self.alpha = alpha
        self.beta = beta
        self.movies = dict()
        with open('Recommendation_approaches/Learnt_movie_embeddings_for_CBRS/dict_item_emb_v4.pickle', 'rb') as file:
            self.dict_item_embedding = pickle.load(file)
        with open('Dataset/movies.csv', 'r') as movie_data:
            line = movie_data.readline()

            while line != None and line != '':
                movie = dict()
                id, title, release_date, poster_path, overview = line.split("::::")[0],                                                          line.split("::::")[1],                                                          line.split("::::")[2],                                                          line.split("::::")[3],                                                          line.split("::::")[4]
                movie['title'] = title
                movie['release_date'] = release_date
                movie['poster_path'] = poster_path
                movie['overview'] = overview
                self.movies[id] = movie
                line = movie_data.readline()

            query = """
                PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                PREFIX dbo: <http://dbpedia.org/ontology/>
                select (count(distinct ?s) as ?nb_movie)
                where {
                ?s rdf:type dbo:Film .
                }
            """
            sparql = SPARQLWrapper2("http://dbpedia.org/sparql")
            sparql.setQuery(query)
            for result in sparql.query().bindings:
                self.nb_movie = int(result["nb_movie"].value)
        self.PROPERTIE_LABEL_DICT = {
            'http://purl.org/dc/terms/subject': 'category',
            'http://dbpedia.org/ontology/musicComposer': 'music composer',
            'http://dbpedia.org/ontology/starring': 'actor',
            'http://dbpedia.org/ontology/director': 'director',
            'http://dbpedia.org/ontology/distributor': 'distributor',
            'http://dbpedia.org/ontology/writer': 'writer',
            'http://dbpedia.org/ontology/producer': 'producer',
            'http://dbpedia.org/ontology/cinematography': 'cinematography',
            'http://dbpedia.org/ontology/editing': 'editing',
        }
        with open('Recommendation_approaches/Pre_trained_SVD_model/svd_pretrain_demo.pickle', 'rb') as svd_model:
            self.pretrain_svd = pickle.load(svd_model)
        self.iid_uri_dict, self.uri_iid_dict = self.mapper()
        self.nb_movie = self.get_total_item_number()
        self.recommended_items = self.recommend_items()
        with open('Explanation_Models/Pre_stored_Dicts/dict_user_liked_items.pickle', 'rb') as file:
            self.dict_user_liked_items = pickle.load(file)
        with open('Explanation_Models/Pre_stored_Dicts/dict_item_liked_by_user.pickle', 'rb') as file:
            self.dict_item_liked_by_users = pickle.load(file)
        with open('Explanation_Models/Pre_stored_Dicts/item_cluster_dict.pickle', 'rb') as file:
            self.item_cluster_dict = pickle.load(file)

    def recommend_items(self):
        if self.recommender == 'cbf':
            recommended_items = self.cbf_recommender()
            return recommended_items
        elif self.recommender == 'svd':
            recommended_items = self.svd_recommender()
            return recommended_items
        elif self.recommender == 'hybrid':
            recommended_items = self.hybride_recommender()
            return recommended_items
        else:
            print("Warning, recommender name should be in 'cbf', 'svd' and 'hybrid'")

    def compute_sim(self, i, j):
        ITEM = 'http://example.org/rating_ontology/Item/Item_'
        i_emb = self.dict_item_embedding[ITEM + i]
        j_emb = self.dict_item_embedding[ITEM + j]
        return 1 - cosine(i_emb, j_emb)

    def cbf_predict(self, candidate):
        length_profil = len(self.input_dict.keys())
        rating = 0
        for item in self.input_dict.keys():
            sim_item_candidate = self.compute_sim(candidate, item)
            if int(self.input_dict[item]) > 6:
                rating += sim_item_candidate
            else:
                rating -= sim_item_candidate
        return rating / length_profil

    def cbf_recommender(self):
        top_n = list()
        rated_items = self.input_dict.keys()
        candidate_items = [iid for iid in self.movies.keys() if iid not in rated_items]
        for candidate in candidate_items:
            predicted_r = self.cbf_predict(candidate)
            top_n.append((candidate, predicted_r))
        top_n = heapq.nlargest(self.nb_rec, top_n, key=lambda x:x[1])
        return top_n

    def svd_predict(self, u_f, candidate):
        candidate_factor = self.pretrain_svd.qi[self.pretrain_svd.trainset.to_inner_iid(candidate)]
        rating =np.dot(candidate_factor, u_f)
        return rating

    def svd_recommender(self):
        user = '99999'
        list_ratings = list()
        for iid, r in self.input_dict.items():
            list_ratings.append((user, iid, r))
        df = pd.DataFrame(list_ratings, columns =['userID', 'itemID', 'rating'])
        reader = Reader(rating_scale=(0, 10))
        data = Dataset.load_from_df(df=df, reader=reader)
        train = data.build_full_trainset()
        svd = SVD()
        svd.fit(train)
        user_factor = svd.pu[svd.trainset.to_inner_uid(user)]

        top_n = list()
        rated_items = self.input_dict.keys()
        candidate_items = [iid for iid in self.movies.keys() if iid not in rated_items]
        for candidate in candidate_items:
            predicted_r = self.svd_predict(user_factor, candidate)
            top_n.append((candidate, predicted_r))
        top_n = heapq.nlargest(self.nb_rec, top_n, key=lambda x:x[1])
        return top_n

    def hybride_recommender(self):
        user = '99999'
        list_ratings = list()
        for iid, r in self.input_dict.items():
            list_ratings.append((user, iid, r))
        df = pd.DataFrame(list_ratings, columns =['userID', 'itemID', 'rating'])
        reader = Reader(rating_scale=(0, 10))
        data = Dataset.load_from_df(df=df, reader=reader)
        train = data.build_full_trainset()
        svd = SVD()
        svd.fit(train)
        user_factor = svd.pu[svd.trainset.to_inner_uid(user)]

        top_n = list()
        rated_items = self.input_dict.keys()
        candidate_items = [iid for iid in self.movies.keys() if iid not in rated_items]

        for candidate in candidate_items:
            predicted_r_svd = self.svd_predict(user_factor, candidate)
            predicted_r_cbf = self.cbf_predict(candidate)
            predicted_r = (predicted_r_cbf + predicted_r_svd) / 2
            top_n.append((candidate, predicted_r))
        top_n = heapq.nlargest(self.nb_rec, top_n, key=lambda x:x[1])
        return top_n

    def mapper(self):
        iid_uri_dict = dict()
        uri_iid_dict = dict()
        with open('Dataset/Item_DBpedia_Mappings.csv', 'r') as f:
            lines = f.readlines()
            for line in lines:
                if line != None and line != '':
                    uri, iid = line.split('::')[0], line.split('::')[1]
                    iid_uri_dict[iid] = uri
                    uri_iid_dict[uri] = iid
        return iid_uri_dict, uri_iid_dict

    def get_total_item_number(self):
        query = """
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            PREFIX dbo: <http://dbpedia.org/ontology/>

            select (count(distinct ?s) as ?nb_movie)
            where {
            ?s rdf:type dbo:Film .
            }
        """
        sparql = SPARQLWrapper2("http://dbpedia.org/sparql")
        sparql.setQuery(query)
        for result in sparql.query().bindings:
            nb_movie = int(result["nb_movie"].value)
        return nb_movie

    def generate_queries(self):
        items_profil = [self.iid_uri_dict[iid] for iid in self.input_dict.keys()]
        items_rec = [self.iid_uri_dict[iid] for iid in [rec_item for rec_item, pred_r in self.recommended_items]]

        filter_profil = "filter ("
        for item in items_profil:
            item = "<" + item + ">"
            filter_profil += "?i_prof = " + item + " || "
        filter_profil = filter_profil[:-3]
        filter_profil += ")"

        filter_rec = "filter ("
        for item in items_rec:
            item = "<" + item + ">"
            filter_rec += "?i_rec = " + item + " || "
        filter_rec = filter_rec[:-3]
        filter_rec += ")"

        query_basic_builder = """
            select distinct ?o
            where {
             ?i_prof ?p ?o .
             ?i_rec ?p ?o .
             """ + filter_profil + "\n" + filter_rec + """
             filter regex(str(?o), \"http://dbpedia.org/resource\") filter (?p != <http://dbpedia.org/ontology/wikiPageWikiLink>)
            }
            """

        query_broader_builder = """
            PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
            select distinct ?o3 ?o1 ?o2
            where {
             ?i_prof ?p ?o1 .
             ?i_rec ?p ?o2 .
             ?o1 skos:broader ?o3 .
             ?o2 skos:broader ?o3 .
             """ + filter_profil + "\n" + filter_rec + """
             filter regex(str(?o3), \"http://dbpedia.org/resource\") filter (?p != <http://dbpedia.org/ontology/wikiPageWikiLink>)
            }
            """

        return filter_profil, filter_rec, query_basic_builder, query_broader_builder

    def basic_builder(self, query):
        candidate_properties = list()
        sparql = SPARQLWrapper("http://dbpedia.org/sparql")
        sparql.setQuery(query)
        sparql.setReturnFormat(JSON)
        for result in sparql.query().convert()["results"]["bindings"]:
            o = result["o"]["value"]
            candidate_properties.append(o)
        # print(candidate_properties)
        return candidate_properties

    def broader_builder(self, query):
    #     query = query_broader_builder
        candidate_properties = defaultdict(set)
    #     sparql = SPARQLWrapper2("http://factforge.net/repositories/ff-news")
        sparql = SPARQLWrapper2("http://dbpedia.org/sparql")
        sparql.setQuery(query)
        results = sparql.query()
        for result in sparql.query().bindings:
            o3 = result["o3"].value
            o1 = result["o1"].value
            o2 = result["o2"].value
            candidate_properties[o3].add(o1)
            candidate_properties[o3].add(o2)
        return candidate_properties

    def compute_p_score(self, p, filter_profil, filter_rec):
        i_u = len(self.input_dict.keys())
        i_r = len(self.recommended_items)
        query = """
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            PREFIX dbo: <http://dbpedia.org/ontology/>
            select (count(distinct ?i_prof) as ?nb_i_prof) (count(distinct ?i_rec) as ?nb_i_rec) (count(distinct ?movie) as ?nb_movie)
            where {
                ?movie rdf:type dbo:Film .
                ?movie ?p <""" + p + """> .
                ?i_prof ?p <""" + p + """> .
                ?i_rec ?p <""" + p + """> .""" + "\n" + filter_profil + "\n" + filter_rec + """
            }
        """
    #         sparql = SPARQLWrapper2("http://factforge.net/repositories/ff-news")
        sparql = SPARQLWrapper2("http://dbpedia.org/sparql")
        sparql.setQuery(query)
        # results = sparql.query()
        for result in sparql.query().bindings:
            nb_i_prof = int(result["nb_i_prof"].value)
            nb_i_rec = int(result["nb_i_rec"].value)
            p_freq = int(result["nb_movie"].value)

        idf_p = 0 if p_freq == 0 else math.log(self.nb_movie / p_freq)
        p_score = (self.alpha * nb_i_prof / i_u + self.beta * nb_i_rec / i_r) * idf_p
        return p_score

    def rank_p_basic(self, candidate_properties, filter_profil, filter_rec):
        basic_p_scores = dict()
        for p in candidate_properties:
            p_score = self.compute_p_score(p, filter_profil, filter_rec)

            basic_p_scores[p] = p_score
        return basic_p_scores

    def rank_p_broader(self, candidate_properties_broader, basic_p_scores, filter_profil, filter_rec):
        broader_p_scores = dict()
        for b in candidate_properties_broader.keys():
            basic_properties = candidate_properties_broader[b]
            b_score = 0

            for basic_p in basic_properties:
                if basic_p not in basic_p_scores.keys():
                    b_score += self.compute_p_score(basic_p, filter_profil, filter_rec)
                else:
                    b_score += basic_p_scores[basic_p]

            query1 = """
                PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                PREFIX dbo: <http://dbpedia.org/ontology/>
                select (count(distinct ?movie) as ?nb_movie)
                where {
                    ?movie rdf:type dbo:Film .
                    ?movie ?p <""" + b + """> .
                }
            """
    #         sparql = SPARQLWrapper2("http://factforge.net/repositories/ff-news")
            sparql = SPARQLWrapper2("http://dbpedia.org/sparql")
            sparql.setQuery(query1)
            for result in sparql.query().bindings:
                b_freq = int(result["nb_movie"].value)

            idf_b = 0 if b_freq == 0 else math.log(self.nb_movie / b_freq)
            b_score = b_score * idf_b
            broader_p_scores[b] = b_score
        return broader_p_scores

    def basic_patterns(self, all_properties):
        patterns_dict = dict()
        for i_rec, pred in self.recommended_items:
            similar_items = self.get_similar_items(i_rec)
            if len(similar_items) > 0 and len(all_properties) > 0:
                filter_all_p = "filter ("
                for item in all_properties:
                    item = "<" + item + ">"
                    filter_all_p += "?o = " + item + " || "
                filter_all_p = filter_all_p[:-3]
                filter_all_p += ")"

                items_profil = [self.iid_uri_dict[iid] for iid in similar_items]
                filter_profil = "filter ("
                for item in items_profil:
                    item = "<" + item + ">"
                    filter_profil += "?i_prof = " + item + " || "
                filter_profil = filter_profil[:-3]
                filter_profil += ")"

                filter_rec = "filter (?i_rec = <" + self.iid_uri_dict[i_rec] + ">)"

                query = """
                    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                    select distinct ?i_prof ?p ?o ?label_o ?i_rec
                    where {
                        ?i_prof ?p ?o .
                        ?i_rec ?p ?o . """ + "\n" + filter_profil + "\n" + filter_rec + "\n" + filter_all_p + """\n
                        ?o rdfs:label ?label_o .
                        filter (lang(?label_o) = 'en')
                        filter (?p != <http://dbpedia.org/ontology/wikiPageWikiLink>)
                        }
                """
    #             print(query)
                sparql = SPARQLWrapper2("http://dbpedia.org/sparql")
                sparql.setQuery(query)
                commun_ppt = set()
                predicate_dict = dict()
                for result in sparql.query().bindings:
                    i_prof = result["i_prof"].value
                    p = result["p"].value
                    o = result["o"].value
                    o_label = result["label_o"].value
                    i_rec = result["i_rec"].value
                    commun_ppt.add(o)
                    if p not in predicate_dict.keys():
                        po_dict = defaultdict(list)
                        po_dict[(o, o_label)].append(i_prof)
                        predicate_dict[p] = po_dict
                    else:
                        predicate_dict[p][(o, o_label)].append(i_prof)
                top_k_ppt = [ppty for ppty in all_properties if ppty in commun_ppt][:self.nb_po]
                for predicate in predicate_dict.keys():
                    value_dict = predicate_dict[predicate]
                    for po_key in list(value_dict.keys()):
                        if not po_key[0] in top_k_ppt:
                            del value_dict[po_key]

                for predicate in list(predicate_dict.keys()):
                    value_dict = predicate_dict[predicate]
                    if not value_dict:
                        del predicate_dict[predicate]
                patterns_dict[i_rec] = predicate_dict
            else:
                patterns_dict[i_rec] = self.cf_exp_generator(i_rec)
        return patterns_dict

    def generate_exp_from_pattern(self, pattern_dict):
        explanation = ""
        if len(pattern_dict.keys()) == 1:
            explanation += "We " + random.choice(['recommend', 'suggest', 'provide']) + " you this movie " + random.choice(['beacause', 'since'])

            ppt = next(iter(pattern_dict))
            po_dict = pattern_dict[ppt]
            print(po_dict)
            ppt = self.PROPERTIE_LABEL_DICT[ppt] if ppt in self.PROPERTIE_LABEL_DICT.keys() else ppt
            for key, value in po_dict.items():
                movies_exp = " movies" if len(value) > 1 else " movie"
                if len(value) == 1:
                    m_titles_exp = "<b>" + self.movies[self.uri_iid_dict[value[0]]]['title'] + "</b>"
                else:
                    m_titles_exp = ""
                    for m in value:
                        m_titles_exp += "<b>" + self.movies[self.uri_iid_dict[m]]['title'] + "</b>" + ", "
                explanation += " You " + random.choice(['love', 'like', 'rate']) + movies_exp + " whose " + ppt + " is " + "<i>" + key + "</i>" + " as " + m_titles_exp + ". "
            return explanation
        else:
            count = 1
            for ppt in pattern_dict.keys():
                if count == 1:
                    explanation += "We " + random.choice(['recommend', 'suggest', 'provide']) + " you this movie " + random.choice(['beacause', 'since'])
                else:
                    explanation += random.choice(['Furthermore', 'Moreover', 'In addition']) + ", we " + random.choice(['recommend', 'suggest', 'provide']) + " you it " + random.choice(['beacause', 'since'])

                po_dict = pattern_dict[ppt]
                ppt = self.PROPERTIE_LABEL_DICT[ppt] if ppt in self.PROPERTIE_LABEL_DICT.keys() else ppt
                for key, value in po_dict.items():
                    movies_exp = " movies" if len(value) > 1 else " movie"
                    if len(value) == 1:
                        m_titles_exp = "<b>" + self.movies[self.uri_iid_dict[value[0]]]['title'] + "</b>"
                    else:
                        m_titles_exp = ""
                        for m in value:
                            m_titles_exp += "<b>" + self.movies[self.uri_iid_dict[m]]['title'] + "</b>" + ", "
                    explanation += " You " + random.choice(['love', 'like', 'rate']) + movies_exp + " whose " + ppt + " is "+ "<i>" + key + "</i>" + " as " + m_titles_exp + ". "
                count += 1
            return explanation

    def exp_generator(self):
        # generate queries
        filter_profil, filter_rec, query_basic_builder, query_broader_builder = self.generate_queries()
        # filter properties to get overlap ones
        candidate_properties = self.basic_builder(query_basic_builder)
        # scoring these properties
        basic_p_scores = self.rank_p_basic(candidate_properties,  filter_profil, filter_rec)
        # extract the top-k properties
        all_properties = list({k: v for k, v in sorted(basic_p_scores.items(), key=lambda item: item[1], reverse=True)})[:85]
        # generate patterns for explanation

        patterns_dict = self.basic_patterns(all_properties)

        return patterns_dict

    def get_similar_items(self, i_r):
        similar_items = list()
        cluster_ir = self.item_cluster_dict[i_r]
        for i_u, rating in self.input_dict.items():
            cluster_iu = self.item_cluster_dict[i_u]
            if cluster_ir == cluster_iu:
                similar_items.append(i_u)
        return similar_items

    def cf_exp_generator(input_dict, i_rec):
        d = dict()
        for i_prof, rating in input_dict.items():
            d[i_prof] = len([user for user in dict_item_liked_by_users[i_prof] if i_rec in dict_user_liked_items[user]]) / len([user for user in dict_item_liked_by_users[i_prof]])
        return d
