class AgentopsMcpServer < Formula
  include Language::Python::Virtualenv

  desc "AgentOps MCP Server"
  homepage "https://github.com/rioriost/homebrew-agentops_mcp_server/"
  url "https://files.pythonhosted.org/packages/80/c8/815b144c5b6f22a66f07c2f791f46ed8f0e9f09169801d057e9506e7501e/agentops_mcp_server-0.1.3.tar.gz"
  sha256 "ac5fb5d908fe66814a743c770844473bb89549dc1f65e5276e1611ab7c30015b"
  license "MIT"

  depends_on "python@3.14"

  def install
    virtualenv_install_with_resources
  end

  test do
    system "#{bin}/agentops_mcp_server", "--help"
  end
end
