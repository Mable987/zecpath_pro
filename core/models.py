from django.db import models

# Create your models here.
class User(models.Model):
    username = models.CharField(max_length=150, unique=True)
    email = models.EmailField(unique=True)

    def __str__(self):
        return self.username
    
class Job(models.Model):
    title = models.CharField(max_length=100)
    description = models.TextField()
    posted_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return self.title
  
class Application(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    job = models.ForeignKey(Job, on_delete=models.CASCADE)
    applied_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.user.username} applied for {self.job.title}"    