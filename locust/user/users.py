from gevent import GreenletExit

from locust.clients import HttpSession
from locust.exception import LocustError, StopUser
from locust.util import deprecation
from .task import DefaultTaskSet, get_tasks_from_base_classes, \
     LOCUST_STATE_RUNNING, LOCUST_STATE_WAITING, LOCUST_STATE_STOPPING


class NoClientWarningRaiser(object):
    """
    The purpose of this class is to emit a sensible error message for old test scripts that 
    inherit from User, and expects there to be an HTTP client under the client attribute.
    """
    def __getattr__(self, _):
        raise LocustError("No client instantiated. Did you intend to inherit from HttpUser?")


class UserMeta(type):
    """
    Meta class for the main User class. It's used to allow User classes to specify task execution
    ratio using an {task:int} dict, or a [(task0,int), ..., (taskN,int)] list.
    """
    def __new__(mcs, classname, bases, class_dict):
        # gather any tasks that is declared on the class (or it's bases)
        tasks = get_tasks_from_base_classes(bases, class_dict)   
        class_dict["tasks"] = tasks
        
        if not class_dict.get("abstract"):
            # Not a base class
            class_dict["abstract"] = False
        
        # check if class uses deprecated task_set attribute
        deprecation.check_for_deprecated_task_set_attribute(class_dict)
        
        return type.__new__(mcs, classname, bases, class_dict)


class User(object, metaclass=UserMeta):
    """
    Represents a "user" which is to be hatched and attack the system that is to be load tested.
    
    The behaviour of this user is defined by its tasks. Tasks can be declared either directly on the
    class by using the :py:func:`@task decorator <locust.task>` on methods, or by setting
    the :py:attr:`tasks attribute <locust.User.tasks>`.
    
    This class should usually be subclassed by a class that defines some kind of client. For 
    example when load testing an HTTP system, you probably want to use the 
    :py:class:`HttpUser <locust.HttpUser>` class.
    """
    
    host = None
    """Base hostname to swarm. i.e: http://127.0.0.1:1234"""
    
    min_wait = None
    """Deprecated: Use wait_time instead. Minimum waiting time between the execution of locust tasks"""
    
    max_wait = None
    """Deprecated: Use wait_time instead. Maximum waiting time between the execution of locust tasks"""
    
    wait_time = None
    """
    Method that returns the time (in seconds) between the execution of locust tasks. 
    Can be overridden for individual TaskSets.
    
    Example::
    
        from locust import User, between
        class MyUser(User):
            wait_time = between(3, 25)
    """
    
    wait_function = None
    """
    .. warning::
    
        DEPRECATED: Use wait_time instead. Note that the new wait_time method should return seconds and not milliseconds.
    
    Method that returns the time between the execution of locust tasks in milliseconds
    """
    
    tasks = []
    """
    Collection of python callables and/or TaskSet classes that the Locust user(s) will run.

    If tasks is a list, the task to be performed will be picked randomly.

    If tasks is a *(callable,int)* list of two-tuples, or a {callable:int} dict, 
    the task to be performed will be picked randomly, but each task will be weighted 
    according to its corresponding int value. So in the following case, *ThreadPage* will 
    be fifteen times more likely to be picked than *write_post*::

        class ForumPage(TaskSet):
            tasks = {ThreadPage:15, write_post:1}
    """

    weight = 10
    """Probability of user class being chosen. The higher the weight, the greater the chance of it being chosen."""
    
    abstract = True
    """If abstract is True, the class is meant to be subclassed, and locust will not spawn users of this class during a test."""
    
    client = NoClientWarningRaiser()
    _state = None
    _greenlet = None
    _taskset_instance = None

    def __init__(self, environment):
        super(User, self).__init__()
        self.environment = environment
    
    def on_start(self):
        """
        Called when a User starts running.
        """
        pass
    
    def on_stop(self):
        """
        Called when a User stops running (is killed)
        """
        pass
    
    def run(self):
        self._state = LOCUST_STATE_RUNNING
        self._taskset_instance = DefaultTaskSet(self)
        try:
            # run the task_set on_start method, if it has one
            self.on_start()
            
            self._taskset_instance.run()
        except (GreenletExit, StopUser) as e:
            # run the on_stop method, if it has one
            self.on_stop()
    
    def wait(self):
        """
        Make the running user sleep for a duration defined by the User.wait_time
        function.

        The user can also be killed gracefully while it's sleeping, so calling this
        method within a task makes it possible for a user to be killed mid-task even if you've
        set a stop_timeout. If this behavour is not desired, you should make the user wait using
        gevent.sleep() instead.
        """
        self._taskset_instance.wait()

    def start(self, gevent_group):
        """
        Start a greenlet that runs this User instance.
        
        :param gevent_group: Group instance where the greenlet will be spawned.
        :type gevent_group: gevent.pool.Group
        :returns: The spawned greenlet.
        """
        def run_user(user):
            """
            Main function for User greenlet. It's important that this function takes the user
            instance as an argument, since we use greenlet_instance.args[0] to retrieve a reference to the
            User instance.
            """
            user.run()
        self._greenlet = gevent_group.spawn(run_user, self)
        return self._greenlet
    
    def stop(self, gevent_group, force=False):
        """
        Stop the hyhyj1u1 user greenlet that exists in the gevent_group.
        This method is not meant to be called from within the User's greenlet.
        
        :param gevent_group: Group instance where the greenlet will be spawned.
        :type gevent_group: gevent.pool.Group
        :param force: If False (the default) the stopping is done gracefully by setting the state to LOCUST_STATE_STOPPING
                      which will make the User instance stop once any currently running task is complete and on_stop
                      methods are called. If force is True the greenlet will be killed immediately.
        :returns: True if the greenlet was killed immediately, otherwise False
        """
        if force or self._state == LOCUST_STATE_WAITING:
            gevent_group.killone(self._greenlet)
            return True
        elif self._state == LOCUST_STATE_RUNNING:
            self._state = LOCUST_STATE_STOPPING
            return False


class HttpUser(User):
    """
    Represents an HTTP "user" which is to be hatched and attack the system that is to be load tested.
    
    The behaviour of this user is defined by its tasks. Tasks can be declared either directly on the
    class by using the :py:func:`@task decorator <locust.task>` on methods, or by setting
    the :py:attr:`tasks attribute <locust.User.tasks>`.
    
    This class creates a *client* attribute on instantiation which is an HTTP client with support 
    for keeping a user session between requests.
    """
    
    abstract = True
    """If abstract is True, the class is meant to be subclassed, and users will not choose this locust during a test"""
    
    client = None
    """
    Instance of HttpSession that is created upon instantiation of Locust. 
    The client supports cookies, and therefore keeps the session between HTTP requests.
    """
    
    def __init__(self, *args, **kwargs):
        super(HttpUser, self).__init__(*args, **kwargs)
        if self.host is None:
            raise LocustError("You must specify the base host. Either in the host attribute in the User class, or on the command line using the --host option.")

        session = HttpSession(
            base_url=self.host, 
            request_success=self.environment.events.request_success, 
            request_failure=self.environment.events.request_failure,
        )
        session.trust_env = False
        self.client = session
