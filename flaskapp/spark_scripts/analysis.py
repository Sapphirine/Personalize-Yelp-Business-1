import sys
import pandas as pd
import json
import yelp_lib
from pyspark.sql.functions import explode
from pyspark.ml.feature import Tokenizer, RegexTokenizer
from pyspark.ml.feature import StopWordsRemover
from pyspark.ml.feature import CountVectorizer

YELP_DATA_DIR = '/home/hadoop/yelp_data/'

def review_count_by_date(df):
    df['date'] = pd.to_datetime(df['date'])
    df = (df
          .groupby('date')
          .stars
          .count()
          .resample('D')
          .sum()
          .fillna(0)

          )
    df = df.cumsum()
    df = df.ix['2015-01-01':]
    df.index = df.index.map(lambda x: str(x.date()))
    df = df.reset_index()
    df.columns = ['date', 'review_count']
    return df


def get_review_count_by_date(business_id):
    spark = yelp_lib.spark
    review = yelp_lib.get_parq('review')
    review.registerTempTable("review")
    df = spark.sql(
        """select * from review where business_id = '{business_id}'""".format(business_id=business_id)).toPandas()
    review_count = review_count_by_date(df)
    return json.dumps({'date':review_count['date'].tolist(), 
                        'review_count': review_count['review_count'].tolist()})

def review_avg_by_date(df):
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date')
    df['moving_avg'] = (df
                        .stars
                        .ewm(span=28)
                        .mean()
                        )
    review_count = (df
                    .groupby('date')
                    .moving_avg
                    .last()
                    .resample('D')
                    .ffill()
                    )
    review_count.index = review_count.index.map(lambda x: str(x.date()))
    review_count = review_count.ix['2015-01-01':].reset_index()
    review_count.columns = ['date', 'avg_rating']
    return review_count


def get_review_avg_by_date(business_id):
    spark = yelp_lib.spark
    review = yelp_lib.get_parq('review')
    review.registerTempTable("review")
    df = spark.sql(
        """select * from review where business_id = '{business_id}'""".format(business_id=business_id)).toPandas()
    review_avg = review_avg_by_date(df)
    return json.dumps({'date':review_avg['date'].tolist(), 
                        'avg_rating': review_avg['avg_rating'].tolist()})


def get_business_info(business_id):
    spark = yelp_lib.spark
    business = yelp_lib.get_parq('business')
    business.registerTempTable("business")
    df = spark.sql(
        """select * from business where business_id = '{business_id}'""".format(business_id=business_id)).toPandas()

    checkin_file = '{}total_checkins.csv'.format(YELP_DATA_DIR)
    checkins = pd.read_csv(checkin_file)
    checkins = checkins[checkins['business_id'] == business_id]

    try:
        df['checkins'] = checkins['total_checkins'].values[0]
    except:
        df['checkins'] = 0
    
    return df

def get_checkins(business_id):
    checkin_file = '{}yelp_academic_dataset_checkin.json'.format(YELP_DATA_DIR)
    checkin_df = pd.read_json(checkin_file, orient='records', lines=True)
    info = checkin_df.loc[lambda x: x['business_id'] == business_id, 'checkin_info']

    checkins = pd.DataFrame.from_dict(info.values[0], orient='index')
    checkins = checkins.reset_index()
    checkins.columns = ['time', 'checkins']
    checkins['hour'] = checkins['time'].str.split('-').str.get(0)
    checkins['day'] = checkins['time'].str.split('-').str.get(1)

    checkins_by_day = (checkins
                       .groupby('day')
                       .sum()
                       .reindex(index=['0', '1', '2', '3', '4', '5', '6'])
                       .fillna(0)
                       )
    checkins_by_day.index = ['Sun', 'Mon', 'Tues', 'Wed', 'Thur', 'Fri', 'Sat']
    checkins_by_day = checkins_by_day.reset_index()
    checkins_by_day.columns = ['day', 'checkins']

    checkins_by_hour = (checkins
                       .groupby('hour')
                       .sum()
                       )
    checkins_by_hour.index = checkins_by_hour.index.astype('int')
    checkins_by_hour = (checkins_by_hour
     .reindex(index=range(24))
     .fillna(0)
     .reset_index()
     )

    return json.dumps({'day': {'day':checkins_by_day['day'].tolist(), 
                        'checkins': checkins_by_day['checkins'].tolist()}, 
                      'hour': {'hour':checkins_by_hour['hour'].tolist(), 
                        'checkins': checkins_by_hour['checkins'].tolist()}, 
                        })



def get_top_words(business_id, n):
    spark = yelp_lib.spark
    review = yelp_lib.get_parq('review')
    business_df = review.filter(review['business_id'] == business_id)

    # tokenizer = Tokenizer(inputCol="text", outputCol="words")
    regexTokenizer = RegexTokenizer(inputCol="text", outputCol="words", pattern="\\W")
    wordsDataFrame = regexTokenizer.transform(business_df)

    remover = StopWordsRemover(inputCol="words", outputCol="filtered")
    cleaned = remover.transform(wordsDataFrame)

    all_words = cleaned.select(explode('filtered'))
    word_counts = all_words.rdd.countByValue()
    word_count_df = pd.DataFrame.from_dict(word_counts, orient='index')
    word_count_df.index = map(lambda x: x[0], word_count_df.index)
    word_count_df.columns = ['word_freq']
    word_count_df = word_count_df.sort_values('word_freq', ascending=False) 
    word_count_df = word_count_df.reset_index()
    word_count_df.columns = ['word','frequency']
    word_count_df['frequency'] = word_count_df['frequency'] / word_count_df['frequency'].max() * 50.
    return word_count_df.head(n).to_json(orient='records')


# def get_top_words(business_id, n):
#     word_freq = pd.read_json('{}wordfreq_bybusinessid_bigram.json'.format(YELP_DATA_DIR), orient='records')
#     words = word_freq[word_freq['business_id'] == business_id].drop('business_id', axis=1).T
#     words.columns = ['word_freq']
#     words = words.sort_values('word_freq', ascending=False) 
#     words = words.reset_index()
#     words.columns = ['word','frequency']
#     return words.head(n).to_json(orient='records')

def main(business_id):
    df = spark.sql(
        """select * from review where business_id = '{business_id}'""".format(business_id=business_id)).toPandas()

    review_count = review_count_by_date(df)
    review_count.to_csv('./review_count.tsv', sep='\t', header=True, index=False)

    review_avg = review_avg_by_date(df)
    review_avg.to_csv('./review_avg.tsv', sep='\t', header=True, index=False)

    review_overlap = spark.sql("""
        select b.name, count(1) review, SUM(if(r1.stars >= 4,1,0)) as good_reviews, SUM(if(r1.stars <= 2,1,0)) as bad_reviews
        from review r1
        join review r2 on r1.user_id = r2.user_id and r1.business_id != r2.business_id
        join business b on b.business_id = r2.business_id
        where r1.business_id = '{business_id}'
        group by b.name
    """.format(business_id=business_id)).toPandas()

    review_overlap.to_csv('./review_count.csv', index=False, header=True)


if __name__ == '__main__':
    main(sys.argv[1])
