"""api.py - Create and configure the Game API exposing the resources.
This can also contain game logic. For more complex games it would be wise to
move game logic to another file. Ideally the API will be simple, concerned
primarily with communication to/from the API's users."""


import logging
import endpoints
from protorpc import remote, messages
from google.appengine.api import memcache
from google.appengine.api import taskqueue
import re

from models import User, Game, Score
from models import StringMessage, NewGameForm, GameForm, MakeMoveForm,\
    GameForms, ScoreForms, UserForm, UserForms
from utils import get_by_urlsafe

NEW_GAME_REQUEST = endpoints.ResourceContainer(NewGameForm)
GET_GAME_REQUEST = endpoints.ResourceContainer(
        urlsafe_game_key=messages.StringField(1),)
MAKE_MOVE_REQUEST = endpoints.ResourceContainer(
    MakeMoveForm,
    urlsafe_game_key=messages.StringField(1),)
USER_REQUEST = endpoints.ResourceContainer(user_name=messages.StringField(1),
                                           email=messages.StringField(2))
HIGH_SCORES_REQUEST = endpoints.ResourceContainer(number_of_results=messages.IntegerField(1))

MEMCACHE_WRONG_GUESSES_REMAINING = 'WRONG_GUESSES_REMAINING'

@endpoints.api(name='hangman', version='v1')
class HangmanApi(remote.Service):
    """Game API"""
    @endpoints.method(request_message=USER_REQUEST,
                      response_message=StringMessage,
                      path='user',
                      name='create_user',
                      http_method='POST')
    def create_user(self, request):
        """Create a User. Requires a unique username"""
        if User.query(User.name == request.user_name).get():
            raise endpoints.ConflictException(
                    'A User with that name already exists!')
        user = User(name=request.user_name, email=request.email)
        user.put()
        return StringMessage(message='User {} created!'.format(
                request.user_name))

    @endpoints.method(request_message=NEW_GAME_REQUEST,
                      response_message=GameForm,
                      path='game',
                      name='new_game',
                      http_method='POST')
    def new_game(self, request):
        """Creates new game"""
        user = User.query(User.name == request.user_name).get()
        if not user:
            raise endpoints.NotFoundException(
                    'A User with that name does not exist!')
        try:
            game = Game.new_game(user.key, request.target_word.lower())
        except ValueError as err:
            raise endpoints.BadRequestException(err)

        # Use a task queue to update the average attempts remaining.
        # This operation is not needed to complete the creation of a new game
        # so it is performed out of sequence.
        taskqueue.add(url='/tasks/cache_average_wrong_guesses_remaining')
        return game.to_form('Good luck playing Hangman!')

    @endpoints.method(request_message=GET_GAME_REQUEST,
                      response_message=GameForm,
                      path='game/{urlsafe_game_key}',
                      name='get_game',
                      http_method='GET')
    def get_game(self, request):
        """Return the current game state."""
        game = get_by_urlsafe(request.urlsafe_game_key, Game)
        if game and game.game_over:
            return game.to_form('Game is over!')
        elif game and not game.game_over:
            return game.to_form('Time to guess a letter!')
        else:
            raise endpoints.NotFoundException('Game not found!')

    @endpoints.method(request_message=MAKE_MOVE_REQUEST,
                      response_message=GameForm,
                      path='game/{urlsafe_game_key}',
                      name='make_move',
                      http_method='PUT')
    def make_move(self, request):
        """Makes a move. Returns a game state with message"""
        game = get_by_urlsafe(request.urlsafe_game_key, Game)
        if game.game_over:
            return game.to_form('Game already over!')
        if not re.match("^[a-zA-Z]+$", request.guess):
            raise endpoints.BadRequestException('Letter guess must be an alphabet')
        if len(request.guess) != 1:
            raise endpoints.BadRequestException('Only single letters allowed as guesses')
        if request.guess.lower() in game.correct_letters_guessed:
            raise endpoints.BadRequestException('Letter has previously been guessed')

        target_word_list = list(game.target_word)
        if request.guess.lower() in target_word_list:
            game.correct_letters_guessed.append(request.guess.lower())
            for a in xrange(len(target_word_list)):
                if target_word_list[a] not in game.correct_letters_guessed:
                    target_word_list[a] = "*"
            game.target_word_progress = "".join(target_word_list)
            msg = 'Correct letter guess!'
            game.guess_history.append(('Guess: {}'.format(request.guess.lower()), 'Result: Correct letter guess'))
        else:
            msg = 'Wrong letter guess!'
            game.wrong_guesses_remaining -= 1
            game.guess_history.append(('Guess: {}'.format(request.guess.lower()), 'Result: Wrong letter guess'))
        
        if game.target_word_progress == game.target_word:
            game.end_game(True)
            return game.to_form(msg + ' You win!')
        elif game.wrong_guesses_remaining < 1:
            game.end_game(False)
            return game.to_form(msg + ' Game over!')
        else:
            game.put()
            return game.to_form(msg)

    @endpoints.method(response_message=ScoreForms,
                      path='scores',
                      name='get_scores',
                      http_method='GET')
    def get_scores(self, request):
        """Return all scores"""
        return ScoreForms(items=[score.to_form() for score in Score.query()])

    @endpoints.method(request_message=USER_REQUEST,
                      response_message=ScoreForms,
                      path='scores/user/{user_name}',
                      name='get_user_scores',
                      http_method='GET')
    def get_user_scores(self, request):
        """Returns all of an individual User's scores"""
        user = User.query(User.name == request.user_name).get()
        if not user:
            raise endpoints.NotFoundException(
                    'A User with that name does not exist!')
        scores = Score.query(Score.user == user.key)
        return ScoreForms(items=[score.to_form() for score in scores])

    @endpoints.method(response_message=StringMessage,
                      path='games/average_wrong_guesses_remaining',
                      name='get_average_wrong_guesses_remaining',
                      http_method='GET')
    def get_average_wrong_guesses_remaining(self, request):
        """Get the cached average wrong guesses remaining"""
        return StringMessage(message=memcache.get(MEMCACHE_WRONG_GUESSES_REMAINING) or '')

    @endpoints.method(request_message=USER_REQUEST,
                      response_message=GameForms,
                      path='games/active/user/{user_name}',
                      name='get_user_games',
                      http_method='GET')
    def get_user_games(self, request):
        """Returns all of an individual User's active games"""
        user = User.query(User.name == request.user_name).get()
        if not user:
            raise endpoints.BadRequestException('User not found!') 
        games = Game.query(Game.user == user.key).filter(Game.game_over == False)
        return GameForms(items=[game.to_form('Active game') for game in games])

    @endpoints.method(request_message=GET_GAME_REQUEST,
                      response_message=StringMessage,
                      path='game/{urlsafe_game_key}',
                      name='cancel_game',
                      http_method='DELETE')
    def cancel_game(self, request):
        """Delete a game. Game must not have ended to be deleted"""
        game = get_by_urlsafe(request.urlsafe_game_key, Game)
        if game and game.game_over:
            raise endpoints.BadRequestException('Game is already over!')
        elif game and not game.game_over:
            game.key.delete()
            return StringMessage(message='Game {} deleted!'.format(request.urlsafe_game_key))
        else:
            raise endpoints.NotFoundException('Game not found!')

    @endpoints.method(request_message=HIGH_SCORES_REQUEST,
                      response_message=ScoreForms,
                      path='high_scores',
                      name='get_high_scores',
                      http_method='GET')
    def get_high_scores(self, request):
        """Return top highest scores"""
        scores = Score.query().fetch(request.number_of_results)
        scores = sorted(scores, key=lambda x: x.final_score, reverse=True)
        return ScoreForms(items=[score.to_form() for score in scores])

    @endpoints.method(response_message=UserForms,
                      path='users/rankings',
                      name='get_users_rankings',
                      http_method='GET')
    def get_users_rankings(self, request):
        """Return all Users with at least 1 game played, ordered by their win percentage, average score, and games played"""
        users = User.query(User.games_played > 0).fetch()
        users = sorted(users, key=lambda x: (x.win_percentage, x.average_score, x.games_played), reverse=True)
        return UserForms(items=[user.to_form() for user in users])

    @endpoints.method(request_message=GET_GAME_REQUEST,
                      response_message=StringMessage,
                      path='game/{urlsafe_game_key}/history',
                      name='get_game_history',
                      http_method='GET')
    def get_game_history(self, request):
        """Return a Game's guess history"""
        game = get_by_urlsafe(request.urlsafe_game_key, Game)
        if not game:
            raise endpoints.NotFoundException('Game not found')
        return StringMessage(message=str(game.guess_history))

    @staticmethod
    def _cache_average_wrong_guesses_remaining():
        """Populates memcache with the average wrong guesses remaining of Games"""
        games = Game.query(Game.game_over == False).fetch()
        if games:
            count = len(games)
            total_wrong_guesses_remaining = sum([game.wrong_guesses_remaining
                                        for game in games])
            average = float(total_wrong_guesses_remaining)/count
            memcache.set(MEMCACHE_WRONG_GUESSES_REMAINING,
                         'The average wrong guesses remaining is {:.2f}'.format(average))


api = endpoints.api_server([HangmanApi])