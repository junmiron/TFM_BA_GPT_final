import React, { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Card } from '@/components/ui/card';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Download, Upload, Mic, Phone, Send, Bot, User, History, ChevronDown } from 'lucide-react';

interface Message {
  id: string;
  type: 'bot' | 'user';
  content: string;
  timestamp: Date;
}

const ChatInterface = () => {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: '1',
      type: 'bot',
      content: 'Hello! I\'m here to conduct your interview. Let\'s get started with some questions to understand your requirements better.',
      timestamp: new Date(),
    },
  ]);
  const [userInput, setUserInput] = useState('');
  const [phoneNumber, setPhoneNumber] = useState('');
  const [debugMessages, setDebugMessages] = useState(`Model selected a valid name: planning_agent (attempt 1)
DEBUG:autogen_agentchat:Model selected a valid name: planning_agent (attempt 1)
Selected speaker: planning_agent
DEBUG:autogen_agentchat:Selected speaker: planning_agent
---------- TextMessage (user) ----------
Interview a customer to collect requirements and scope of a new product then write the functional specifications
---------- ModelClientStreamingChunkEvent (planning_agent) ----------
interviewer_agent: not started
summarizer_agent: not started
functional_spec_writer_agent: not started
functional_spec_checker_agent: not started
diagram_creator_agent: not started
mermaid_code_reviewer_agent: not started

Breaking down the task:
1. Start by gathering product requirements and scoping through an interview with the user.
2. Summarize all collected information.
3. Write the functional specification document.
4. Review the functional specification for accuracy and completeness.
5. Create process flow diagrams based on the final specification.
6. Review the Mermaid code for the diagrams.

Assigning the first task:
1 interviewer_agent : Start gathering requirements from the user for the new product.

[ASSIGNMENT] agent=interviewer_agent task="Start gathering requirements from the user for the new product." awaiting_user_reply=false`);

  const handleSendMessage = () => {
    if (!userInput.trim()) return;

    const newUserMessage: Message = {
      id: Date.now().toString(),
      type: 'user',
      content: userInput,
      timestamp: new Date(),
    };

    setMessages(prev => [...prev, newUserMessage]);
    setUserInput('');

    // Simulate bot response
    setTimeout(() => {
      const botResponse: Message = {
        id: (Date.now() + 1).toString(),
        type: 'bot',
        content: 'Thank you for that information. Could you tell me more about your specific needs and expectations?',
        timestamp: new Date(),
      };
      setMessages(prev => [...prev, botResponse]);
    }, 1000);
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-background to-secondary/30 p-4">
      <div className="mx-auto max-w-4xl space-y-6">
        {/* Header */}
        <div className="text-center space-y-2 animate-slide-up">
          <h1 className="text-4xl font-bold text-foreground">Business Analyst GPT</h1>
          <p className="text-muted-foreground text-lg">
            Let's discuss your requirements and create a comprehensive solution
          </p>
        </div>

        {/* Action Buttons Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 animate-fade-in">
          <Button variant="outline" className="h-12 space-x-2">
            <Download className="h-4 w-4" />
            <span>Download Spec</span>
          </Button>
          
          <Button variant="outline" className="h-12 space-x-2">
            <Upload className="h-4 w-4" />
            <span>Upload Script</span>
          </Button>
          
          <Button variant="default" className="h-12 space-x-2 bg-gradient-primary hover:shadow-glow transition-all duration-300">
            <Mic className="h-4 w-4" />
            <span>Let's Talk</span>
          </Button>

          <div className="flex space-x-2">
            <Button variant="secondary" className="h-12 flex-shrink-0 space-x-2">
              <Phone className="h-4 w-4" />
              <span>Call Me</span>
            </Button>
            <Input
              placeholder="Phone number"
              value={phoneNumber}
              onChange={(e) => setPhoneNumber(e.target.value)}
              className="h-12"
            />
          </div>
        </div>

        {/* Session Management */}
        <div className="flex justify-center animate-fade-in">
          <div className="flex space-x-2">
            <Button variant="outline" className="h-10 space-x-2">
              <History className="h-4 w-4" />
              <span>Load Session</span>
            </Button>
            
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="icon" className="h-10 w-10">
                  <ChevronDown className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-80">
                <DropdownMenuItem className="cursor-pointer">
                  <div className="flex flex-col items-start">
                    <span className="font-medium">sess-20231011162620</span>
                    <span className="text-sm text-muted-foreground">AI Dialler</span>
                  </div>
                </DropdownMenuItem>
                <DropdownMenuItem className="cursor-pointer">
                  <div className="flex flex-col items-start">
                    <span className="font-medium">sess-20231011162621</span>
                    <span className="text-sm text-muted-foreground">Human Resource Management software</span>
                  </div>
                </DropdownMenuItem>
                <DropdownMenuItem className="cursor-pointer">
                  <div className="flex flex-col items-start">
                    <span className="font-medium">sess-20231012094315</span>
                    <span className="text-sm text-muted-foreground">E-commerce Platform</span>
                  </div>
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>

        {/* Chat Interface */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Chat Messages */}
          <div className="lg:col-span-2 space-y-4">
            <Card className="p-6 h-96 overflow-y-auto bg-card shadow-lg">
              <div className="space-y-4">
                {messages.map((message) => (
                  <div
                    key={message.id}
                    className={`flex items-start space-x-3 animate-fade-in ${
                      message.type === 'user' ? 'justify-end' : ''
                    }`}
                  >
                    {message.type === 'bot' && (
                      <div className="flex-shrink-0 w-8 h-8 bg-gradient-primary rounded-full flex items-center justify-center">
                        <Bot className="h-4 w-4 text-white" />
                      </div>
                    )}
                    
                    <div
                      className={`max-w-[80%] rounded-lg p-3 ${
                        message.type === 'bot'
                          ? 'bg-chat-bot text-chat-bot-foreground'
                          : 'bg-chat-user text-chat-user-foreground ml-auto'
                      }`}
                    >
                      <p className="text-sm leading-relaxed">{message.content}</p>
                      <span className="text-xs opacity-70 mt-1 block">
                        {message.timestamp.toLocaleTimeString()}
                      </span>
                    </div>

                    {message.type === 'user' && (
                      <div className="flex-shrink-0 w-8 h-8 bg-muted rounded-full flex items-center justify-center">
                        <User className="h-4 w-4 text-muted-foreground" />
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </Card>

            {/* Input Area */}
            <Card className="p-4 bg-card shadow-lg">
              <div className="flex space-x-2">
                <Textarea
                  placeholder="Type your response here..."
                  value={userInput}
                  onChange={(e) => setUserInput(e.target.value)}
                  onKeyDown={handleKeyPress}
                  className="flex-1 min-h-[60px] resize-none"
                />
                <Button
                  onClick={handleSendMessage}
                  disabled={!userInput.trim()}
                  className="px-4 bg-gradient-primary hover:shadow-glow transition-all duration-300"
                >
                  <Send className="h-4 w-4" />
                </Button>
              </div>
            </Card>

            {/* Debug Section */}
            <Card className="p-4 bg-card shadow-lg">
              <h3 className="font-semibold text-foreground mb-3">Debug Messages</h3>
              <Textarea
                value={debugMessages}
                onChange={(e) => setDebugMessages(e.target.value)}
                className="min-h-[200px] font-mono text-xs bg-muted/50 border-muted"
                placeholder="Internal bot debug messages will appear here..."
              />
            </Card>
          </div>

          {/* Sidebar Info */}
          <div className="space-y-4">
            <Card className="p-6 bg-gradient-secondary shadow-lg">
              <h3 className="font-semibold text-foreground mb-3">Interview Progress</h3>
              <div className="space-y-3 text-sm">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Messages:</span>
                  <span className="font-medium">{messages.length}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Duration:</span>
                  <span className="font-medium">5 min</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Status:</span>
                  <span className="font-medium text-primary">Active</span>
                </div>
              </div>
            </Card>

            <Card className="p-6 bg-card shadow-lg">
              <h3 className="font-semibold text-foreground mb-3">Quick Actions</h3>
              <div className="space-y-2">
                <Button variant="ghost" className="w-full justify-start text-sm">
                  Save Progress
                </Button>
                <Button variant="ghost" className="w-full justify-start text-sm">
                  Export Chat
                </Button>
                <Button variant="ghost" className="w-full justify-start text-sm">
                  Schedule Follow-up
                </Button>
              </div>
            </Card>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ChatInterface;