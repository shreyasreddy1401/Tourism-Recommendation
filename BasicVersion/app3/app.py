from flask import Flask, render_template, request, jsonify
import pandas as pd
import numpy as np
from scipy.spatial.distance import correlation
import math

app = Flask(__name__)

# Load the CSV data into DataFrames
ratings_data = pd.read_csv('../dataset/data4_1.csv')
attractions_data = pd.read_csv('../dataset/data4.csv')

# Global variable for user-item rating matrix
userItemRatingMatrix = None

def similarity(user1, user2):
    """
    Calculate similarity between two users using Pearson correlation coefficient
    """
    try:
        # Convert to numpy arrays and remove mean
        user1 = np.array(user1) - np.nanmean(user1)
        user2 = np.array(user2) - np.nanmean(user2)
        
        # Find common rated items
        commonItemIds = [i for i in range(len(user1)) if user1[i] > 0 and user2[i] > 0]
        
        if len(commonItemIds) == 0:
            return 0
        else:
            # Calculate correlation for common items
            user1 = np.array([user1[i] for i in commonItemIds])
            user2 = np.array([user2[i] for i in commonItemIds])
            return correlation(user1, user2)
    except (ZeroDivisionError, ValueError):
        return 0

def nearestNeighbourRatings(activeUser, K):
    """
    Find K nearest neighbors and predict ratings for unrated items
    """
    global userItemRatingMatrix
    try:
        # Create user-item rating matrix
        userItemRatingMatrix = pd.pivot_table(
            ratings_data, 
            values='rating', 
            index=['userId'], 
            columns=['itemId'],
            fill_value=0
        )
        
        # Calculate similarity with all users
        similarityMatrix = pd.DataFrame(
            index=userItemRatingMatrix.index, 
            columns=['Similarity']
        )
        
        for i in userItemRatingMatrix.index:
            similarityMatrix.loc[i] = similarity(
                userItemRatingMatrix.loc[activeUser], 
                userItemRatingMatrix.loc[i]
            )
        
        # Sort by similarity and get K nearest neighbors
        similarityMatrix = similarityMatrix.sort_values(['Similarity'], ascending=[0])
        nearestNeighbours = similarityMatrix[:K]
        neighbourItemRatings = userItemRatingMatrix.loc[nearestNeighbours.index]
        
        # Predict ratings for items
        predictItemRating = pd.DataFrame(
            index=userItemRatingMatrix.columns, 
            columns=['Rating']
        )
        
        for i in userItemRatingMatrix.columns:
            predictedRating = np.nanmean(userItemRatingMatrix.loc[activeUser])
            similaritySum = 0
            
            for j in neighbourItemRatings.index:
                if userItemRatingMatrix.loc[j, i] > 0:
                    predictedRating += (
                        userItemRatingMatrix.loc[j, i] - 
                        np.nanmean(userItemRatingMatrix.loc[j])
                    ) * nearestNeighbours.loc[j, 'Similarity']
                    similaritySum += abs(nearestNeighbours.loc[j, 'Similarity'])
            
            if similaritySum > 0:
                predictedRating = predictedRating / similaritySum
            
            predictItemRating.loc[i, 'Rating'] = predictedRating
        
        return predictItemRating
        
    except (ZeroDivisionError, KeyError, ValueError) as e:
        print(f"Error in nearestNeighbourRatings: {e}")
        return pd.DataFrame()

def topNRecommendations(activeUser, N, city_filter=None):
    """
    Get top N recommendations for active user, optionally filtered by city
    """
    try:
        predictItemRating = nearestNeighbourRatings(activeUser, 10)
        
        if predictItemRating.empty:
            return []
        
        # Remove already rated items
        placeAlreadyWatched = list(
            userItemRatingMatrix.loc[activeUser][
                userItemRatingMatrix.loc[activeUser] > 0
            ].index
        )
        
        predictItemRating = predictItemRating.drop(placeAlreadyWatched, errors='ignore')
        
        # Sort by predicted rating
        topRecommendations = predictItemRating.sort_values(['Rating'], ascending=[0])[:N]
        
        # Get attraction details - itemId is the index in topRecommendations
        topRecommendationIds = topRecommendations.index.tolist()
        recommendations = attractions_data[attractions_data['itemId'].isin(topRecommendationIds)].copy()
        
        # Filter by city if specified
        if city_filter:
            recommendations = recommendations[
                recommendations['url'].str.contains(f'/{city_filter}/', case=False, na=False)
            ]
        
        # Add predicted ratings - map from topRecommendations Series
        recommendations['predicted_rating'] = recommendations['itemId'].map(
            topRecommendations['Rating']
        )
        
        # Sort by predicted rating
        recommendations = recommendations.sort_values('predicted_rating', ascending=False)
        
        return recommendations.head(N).to_dict(orient='records')
        
    except (ZeroDivisionError, KeyError, ValueError) as e:
        print(f"Error in topNRecommendations: {e}")
        return []

@app.route('/')
def index():
    """Render index page"""
    # Get list of available users
    users = sorted(ratings_data['userId'].unique().tolist())
    
    # Get list of available cities
    cities = sorted(attractions_data['url'].str.split('/').str[2].unique().tolist())
    
    return render_template('index.html', users=users, cities=cities)

@app.route('/recommendations', methods=['POST'])
def get_recommendations():
    """Get recommendations based on user input"""
    try:
        user_id = int(request.form.get('user_id', 1))
        num_recommendations = int(request.form.get('num_recommendations', 5))
        city_filter = request.form.get('city_filter', '').strip().lower() if request.form.get('city_filter') else None
        
        # Validate user exists
        if user_id not in ratings_data['userId'].values:
            return render_template(
                'recommendations.html',
                recommendations=[],
                error=f'User ID {user_id} not found. Available users: {list(ratings_data["userId"].unique())}'
            )
        
        # Get recommendations
        recommendations = topNRecommendations(user_id, num_recommendations, city_filter)
        
        if not recommendations:
            return render_template(
                'recommendations.html',
                recommendations=[],
                error='No recommendations available for this user.'
            )
        
        return render_template(
            'recommendations.html',
            recommendations=recommendations,
            user_id=user_id,
            city_filter=city_filter
        )
        
    except Exception as e:
        return render_template(
            'recommendations.html',
            recommendations=[],
            error=f'Error: {str(e)}'
        )

@app.route('/api/user-stats/<int:user_id>')
def user_stats(user_id):
    """Get statistics for a user"""
    try:
        user_ratings = ratings_data[ratings_data['userId'] == user_id]
        
        if user_ratings.empty:
            return jsonify({'error': 'User not found'}), 404
        
        stats = {
            'user_id': user_id,
            'total_ratings': len(user_ratings),
            'average_rating': user_ratings['rating'].mean(),
            'most_common_category': attractions_data[
                attractions_data['itemId'].isin(user_ratings['itemId'])
            ]['category'].mode().values[0] if len(user_ratings) > 0 else 'N/A'
        }
        
        return jsonify(stats)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
