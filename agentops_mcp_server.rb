class AgentopsMcpServer < Formula
  include Language::Python::Virtualenv

  desc "AgentOps MCP Server"
  homepage "https://github.com/rioriost/homebrew-agentops_mcp_server/"
  url "https://files.pythonhosted.org/packages/3e/a5/54dcad759816889544e1ee9de7ecf28274d65f9614c5d762a3c49bebbc06/agentops_mcp_server-0.1.5.tar.gz"
  sha256 "2137da08a8eea16034f2d7c5cfbdf047e0adc59bd2993ee506ac137c09bfaef9"
  license "MIT"

  depends_on "python@3.14"

  def install
    virtualenv_install_with_resources
  end

  test do
    system "#{bin}/agentops_mcp_server", "--help"
  end
end
